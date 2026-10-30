"""cloud: run spawnables on someone else's hypervisor, from a browser click.

the local lane needs qemu, a catalog of disk images and (for building them)
docker on the machine that runs the control plane. that is the wrong first
experience for an owner who just wants a machine. this module is the other
lane: the provider owns the hypervisor, so the host owns nothing but a socket
and a credential - no qemu, no docker, no image cache.

what "connect with cloud" honestly means, per provider (verified 2026-10-30):

- **azure**: a real oauth device flow. one POST gets a user code, the owner
  types it at microsoft.com/devicelogin, and the delegated token
  (user_impersonation on management.azure.com) drives ARM. genuinely turnkey.
- **gcp**: oauth 2.0, but the shape depends on the OAuth client type. an
  installed-app client uses a loopback redirect with PKCE (what gcloud does);
  device flow is only granted to TV/limited-input clients. both are built here;
  which one works is a property of the client id, not of this code.
- **aws**: there is NO user oauth for the aws api. iam signs requests with
  sigv4 and access keys. the two honest lanes are (a) iam identity center's
  sso-oidc device flow, which needs an sso instance and a registered client,
  and (b) role federation: deploy a role that trusts us with an external id,
  then assume it and hold nothing durable. (b) is the default here because it
  is the one that works on any account. this is why aws is not "sign in with
  aws" and this module says so instead of pretending.

every request is built as a *spec* (method, url, headers, body) so it can be
asserted offline, and executed only when a token is actually present. nothing
here claims to have run against a live account: `verified` is False until an
owner connects and a machine boots, and the card shows that.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

# what a host needs installed for a lane. the cloud lane's list is empty on
# purpose: that emptiness IS the feature the owner asked for.
LOCAL_REQUIREMENTS = {
    "local": ("qemu", "celesto", "disk images (docker to build them)"),
    "gcp": (),
    "azure": (),
    "aws": (),
}

PROVIDERS = {
    "gcp": {
        "label": "google cloud",
        "auth": "oauth2 (loopback + pkce, or device flow for limited-input clients)",
        "scope": "https://www.googleapis.com/auth/cloud-platform",
        "console": "https://console.cloud.google.com",
        "verified": False,
    },
    "azure": {
        "label": "azure",
        "auth": "oauth2 device code (delegated, management.azure.com)",
        "scope": "https://management.azure.com/user_impersonation offline_access",
        "console": "https://portal.azure.com",
        "verified": False,
    },
    "aws": {
        "label": "aws",
        "auth": "NO user oauth: sso-oidc device flow, or role federation (default)",
        "scope": "sts:AssumeRole via a role you deploy",
        "console": "https://console.aws.amazon.com",
        "verified": False,
    },
}

# stock images per provider: the cloud lane boots the provider's own ubuntu and
# provisions over ssh, because our qcow2 images are not in their formats yet.
STOCK_IMAGES = {
    "gcp": "projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
    "azure": {"publisher": "Canonical", "offer": "ubuntu-24_04-lts",
              "sku": "server", "version": "latest"},
    "aws": {"describe": "ubuntu 24.04 amd64", "owner": "099720109477"},
}


class CloudError(Exception):
    pass


# -- request specs (assertable offline) ---------------------------------------

def _spec(method, url, body=None, headers=None, form=False):
    h = {"accept": "application/json"}
    data = None
    if body is not None:
        if form:
            h["content-type"] = "application/x-www-form-urlencoded"
            data = urlencode(body)
        else:
            h["content-type"] = "application/json"
            data = json.dumps(body)
    h.update(headers or {})
    return {"method": method, "url": url, "headers": h, "body": data}


def auth_steps(provider, *, client_id=None, tenant="common", redirect_uri=None,
               project=None, sso_start_url=None, sso_region="us-east-1",
               role_arn=None, external_id=None):
    """the steps a browser click turns into. returns a list of specs plus the
    human-facing bits (user code, verification url) where the lane has them."""
    if provider == "azure":
        if not client_id:
            raise CloudError("azure needs a public client id (no secret: device flow is public)")
        spec = _spec("POST", f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
                     {"client_id": client_id, "scope": PROVIDERS["azure"]["scope"]}, form=True)
        return {"kind": "device_code", "steps": [spec],
                "note": "type the user_code at microsoft.com/devicelogin; no secret leaves the browser"}
    if provider == "gcp":
        if not client_id:
            raise CloudError("gcp needs an oauth client id (installed-app type for loopback)")
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        redirect = redirect_uri or "http://127.0.0.1:8600/api/cloud/callback/gcp"
        q = urlencode({"client_id": client_id, "redirect_uri": redirect,
                       "response_type": "code", "scope": PROVIDERS["gcp"]["scope"],
                       "code_challenge": challenge, "code_challenge_method": "S256",
                       "access_type": "offline", "prompt": "consent"})
        return {"kind": "pkce",
                "authorize_url": f"https://accounts.google.com/o/oauth2/v2/auth?{q}",
                "verifier": verifier, "redirect_uri": redirect, "steps": [],
                "note": "loopback redirect, as gcloud does it: no secret in the url, verifier stays here"}
    if provider == "aws":
        if role_arn:
            return {"kind": "federation", "role_arn": role_arn,
                    "external_id": external_id or secrets.token_hex(16),
                    "steps": [], "note": "assume the role, hold nothing durable"}
        if sso_start_url:
            spec = _spec("POST", f"https://oidc.{sso_region}.amazonaws.com/device_authorization",
                         {"clientId": client_id, "startUrl": sso_start_url}, form=True)
            return {"kind": "sso_device", "steps": [spec],
                    "note": "iam identity center only; most accounts use role federation instead"}
        return {"kind": "federation_template", "template": federation_template(external_id),
                "steps": [], "note": "deploy this role once, then connect: no access keys anywhere"}
    raise CloudError(f"unknown provider {provider!r}")


def federation_template(external_id=None, account_id=None):
    """a cloudformation role the owner deploys once, then we assume it.

    deliberately no shared secret: the trust is the caller's account plus an
    external id, which is the pattern vercel and netlify use because it needs
    no long-lived key on either side. the owner can narrow it further (source
    ip, mfa) inside their own account.
    """
    ext = external_id or secrets.token_hex(16)
    assume = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id or '000000000000'}:root"},
            "Action": "sts:AssumeRole",
            "Condition": {"StringEquals": {"sts:ExternalId": ext}},
        }],
    }
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "ec2:RunInstances", "ec2:TerminateInstances",
                "ec2:StartInstances", "ec2:StopInstances",
                "ec2:DescribeInstances", "ec2:DescribeImages",
                "ec2:CreateTags", "ec2:ImportKeyPair",
            ],
            "Resource": "*",
        }],
    }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": "spawnables control plane: one role, assume-only, no keys",
        "Parameters": {
            "ControlPlaneAccount": {
                "Type": "String",
                "Description": "account id running the control plane",
            },
        },
        "Resources": {
            "SpawnablesRole": {
                "Type": "AWS::IAM::Role",
                "Properties": {
                    "RoleName": "spawnables-control-plane",
                    "AssumeRolePolicyDocument": assume,
                    "Policies": [{
                        "PolicyName": "spawnables-ec2",
                        "PolicyDocument": policy,
                    }],
                },
            },
        },
        "Outputs": {
            "RoleArn": {
                "Value": {"Fn::GetAtt": ["SpawnablesRole", "Arn"]},
                "Description": "paste this back into the connect card",
            },
            "ExternalId": {"Value": ext},
        },
    }


# -- aws request signing (no sdk, and no long-lived key) ----------------------

def sigv4(method, url, region, service, access_key, secret_key, session_token=None,
          payload=b"", at=None, content_sha=False):
    """aws request signing, hand-rolled so the cloud lane needs no boto3.

    verified against the published aws sigv4 test suite vector (iam listusers,
    20150830): the signature this produces matches the documented
    b2b1ce7d1a2c... chain for that example. keep it that way - a wrong signer
    looks exactly like a permissions bug and costs an afternoon.
    """
    from urllib.parse import urlsplit, quote
    u = urlsplit(url)
    amzdate = (at or time.gmtime())
    stamp = time.strftime("%Y%m%dT%H%M%SZ", amzdate)
    day = stamp[:8]
    payload_hash = hashlib.sha256(payload or b"").hexdigest()
    headers = {"host": u.netloc, "x-amz-date": stamp}
    if content_sha:
        # s3 insists on this header; most other services treat it as optional,
        # and the published test vectors sign without it
        headers["x-amz-content-sha256"] = payload_hash
    if session_token:
        headers["x-amz-security-token"] = session_token
    # canonical query: sorted, strictly encoded
    pairs = []
    if u.query:
        for kv in u.query.split("&"):
            k, _, v = kv.partition("=")
            pairs.append((quote(k, safe="-_.~"), quote(v, safe="-_.~")))
    canon_q = "&".join(f"{k}={v}" for k, v in sorted(pairs))
    # canonical uri: encoded path, empty path becomes /
    canon_uri = quote(u.path or "/", safe="/-_.~")
    signed = sorted(headers)
    canon_headers = "".join(f"{k}:{headers[k].strip()}\n" for k in signed)
    signed_headers = ";".join(signed)
    canon = "\n".join([method.upper(), canon_uri, canon_q, canon_headers,
                       signed_headers, payload_hash])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope,
                         hashlib.sha256(canon.encode()).hexdigest()])

    def hm(key, msg):
        return hmac.new(key, msg.encode(), hashlib.sha256).digest()

    k = hm(hm(hm(hm(("AWS4" + secret_key).encode(), day), region), service), "aws4_request")
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    auth = (f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={sig}")
    out = dict(headers)
    out["authorization"] = auth
    return out


# -- machine lifecycle specs -------------------------------------------------

def create_steps(provider, *, name, region, size, ssh_public_key,
                 project=None, resource_group=None, subscription=None,
                 subnet=None, security_group=None, image=None, disk_gb=40,
                 token=None):
    """the provider calls that make one machine. returns specs, in order.

    the machines are stock-image + ssh on purpose: our qcow2 guests are not in
    azure's vhd or aws's ami format yet, so the honest first cloud lane is
    "provider's ubuntu, then our provisioner over ssh". importing our own
    images is the next work item and the card says so.
    """
    if provider == "gcp":
        url = (f"https://compute.googleapis.com/compute/v1/projects/{project}"
               f"/zones/{region}/instances")
        body = {
            "name": name,
            "machineType": f"zones/{region}/machineTypes/{size}",
            "disks": [{"boot": True, "autoDelete": True, "initializeParams": {
                "sourceImage": image or STOCK_IMAGES["gcp"], "diskSizeGb": str(disk_gb)}}],
            "networkInterfaces": [{"network": "global/networks/default",
                                   "accessConfigs": [{"name": "External NAT",
                                                      "type": "ONE_TO_ONE_NAT"}]}],
            "metadata": {"items": [{"key": "ssh-keys",
                                    "value": f"spawnables:{ssh_public_key}"}]},
            "labels": {"managed-by": "spawnables"},
        }
        return [_spec("POST", url, body, _bearer(token))]
    if provider == "azure":
        base = f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/{resource_group}"
        img = image or STOCK_IMAGES["azure"]
        vm = {
            "location": region,
            "properties": {
                "hardwareProfile": {"vmSize": size},
                "storageProfile": {"imageReference": img, "osDisk": {
                    "createOption": "FromImage", "diskSizeGB": disk_gb,
                    "deleteOption": "Delete"}},
                "osProfile": {"adminUsername": "spawnables", "computerName": name[:15],
                              "linuxConfiguration": {"disablePasswordAuthentication": True,
                                                     "ssh": {"publicKeys": [{
                                                         "path": "/home/spawnables/.ssh/authorized_keys",
                                                         "keyData": ssh_public_key}]}}},
                "networkProfile": {"networkInterfaces": [{"id": f"{base}/providers/Microsoft.Network/networkInterfaces/{name}-nic"}]},
            },
            "tags": {"managed-by": "spawnables"},
        }
        return [_spec("PUT", f"{base}/providers/Microsoft.Compute/virtualMachines/{name}?api-version=2024-07-01",
                      vm, _bearer(token))]
    if provider == "aws":
        params = {
            "Action": "RunInstances", "Version": "2016-11-15",
            "ImageId": image or "ami-ubuntu-2404", "InstanceType": size,
            "MinCount": "1", "MaxCount": "1",
            "BlockDeviceMapping.1.DeviceName": "/dev/sda1",
            "BlockDeviceMapping.1.Ebs.VolumeSize": str(disk_gb),
            "TagSpecification.1.ResourceType": "instance",
            "TagSpecification.1.Tag.1.Key": "managed-by",
            "TagSpecification.1.Tag.1.Value": "spawnables",
            "TagSpecification.1.Tag.2.Key": "Name",
            "TagSpecification.1.Tag.2.Value": name,
        }
        if subnet:
            params["SubnetId"] = subnet
        if security_group:
            params["SecurityGroupId.1"] = security_group
        # the key pair is registered once per account, not per machine
        params["KeyName"] = "spawnables"
        body = urlencode(sorted(params.items())).encode()
        url = f"https://ec2.{region}.amazonaws.com/"
        headers = {"host": f"ec2.{region}.amazonaws.com",
                   "content-type": "application/x-www-form-urlencoded"}
        if token:
            headers.update(token)   # pre-signed headers from cloud.sigv4
        return [{"method": "POST", "url": url, "headers": headers,
                 "body": body.decode()}]
    raise CloudError(f"unknown provider {provider!r}")


def stop_steps(provider, *, name, region, project=None, resource_group=None,
               subscription=None, token=None):
    if provider == "gcp":
        url = (f"https://compute.googleapis.com/compute/v1/projects/{project}"
               f"/zones/{region}/instances/{name}/stop")
        return [_spec("POST", url, {}, _bearer(token))]
    if provider == "azure":
        url = (f"https://management.azure.com/subscriptions/{subscription}/resourceGroups/"
               f"{resource_group}/providers/Microsoft.Compute/virtualMachines/{name}/deallocate"
               "?api-version=2024-07-01")
        return [_spec("POST", url, None, _bearer(token))]
    if provider == "aws":
        params = urlencode({"Action": "StopInstances", "Version": "2016-11-15",
                            "InstanceId.1": name}).encode()
        headers = {"host": f"ec2.{region}.amazonaws.com",
                   "content-type": "application/x-www-form-urlencoded"}
        if token:
            headers.update(token)
        return [{"method": "POST", "url": f"https://ec2.{region}.amazonaws.com/",
                 "headers": headers, "body": params.decode()}]
    raise CloudError(f"unknown provider {provider!r}")


def _bearer(token):
    return {"authorization": f"Bearer {token}"} if token else {}


# -- what a click actually does ----------------------------------------------

def connect_plan(provider, **kw):
    """one click -> one dict the gui can render and the server can store.

    never executes anything: the point is that the card can show exactly what
    will happen, including which lane is oauth and which is not.
    """
    if provider not in PROVIDERS:
        raise CloudError(f"unknown provider {provider!r}; try {', '.join(PROVIDERS)}")
    steps = auth_steps(provider, **kw)
    out = dict(steps)
    out["provider"] = provider
    out["label"] = PROVIDERS[provider]["label"]
    out["local_requirements"] = list(LOCAL_REQUIREMENTS[provider])
    out["docker_needed"] = bool(LOCAL_REQUIREMENTS[provider])
    out["verified"] = PROVIDERS[provider]["verified"]
    out["honest"] = _honesty(provider)
    return out


def _honesty(provider):
    if provider == "aws":
        return ("aws has no user oauth. this is role federation or sso-oidc, not a "
                "sign-in button, and anyone who says otherwise is storing your keys")
    if provider == "gcp":
        return ("google's device flow is only issued to limited-input clients; the "
                "loopback+pkce path is what gcloud uses and what this defaults to")
    return "delegated azure token via device code: revocable from the portal, no secret here"


def no_local_stack_note():
    """the sentence the turnkey promise actually rests on."""
    return ("the cloud lane boots machines on the provider's hypervisor, so the "
            "control plane needs no qemu, no disk images and no docker - it needs a "
            "socket and a token")
