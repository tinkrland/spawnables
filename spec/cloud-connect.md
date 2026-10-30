# connect with cloud: turnkey without docker

the owner's ask: a click that gives a machine even if the device running this has no docker, no qemu and no disk images. this is that lane, and it works because the provider already owns a hypervisor.

## what it removes from the host

| | local lane | cloud lane |
|---|---|---|
| hypervisor | qemu on this machine | the provider's |
| base images | qcow2 in the catalog, built with docker | provider stock ubuntu |
| docker | required to build images | not used |
| what the control plane needs | qemu, celesto, images | a socket and a token |

`cloud.LOCAL_REQUIREMENTS['azure']` is an empty tuple, and that emptiness is the feature.

## the three providers are not the same thing

this is the part worth being blunt about, because "straight oauth with aws" is not a thing that exists:

- **azure**: real oauth device code flow. one POST returns a `user_code`, the owner types it at microsoft.com/devicelogin, and a delegated token with `user_impersonation` on `management.azure.com` drives ARM. public client, no secret stored. revocable in the portal.
- **gcp**: real oauth, but the flow shape is a property of the OAuth client type: an installed-app client gets a loopback redirect with PKCE (what `gcloud` does), while device flow is only issued to TV/limited-input clients. both are implemented; which one works comes from the client id, not from us.
- **aws**: **no user oauth exists for the aws api.** iam signs every request with sigv4 and access keys. two honest lanes:
  - **role federation (default)**: `cloud.federation_template()` emits a cloudformation template creating one assume-only role, trusted by the control plane's account plus a random external id. deploy it once, paste the arn, and no access key exists anywhere. this is the vercel/netlify pattern and it works on any account.
  - **sso-oidc device flow**: requires IAM Identity Center and a registered client. supported in `auth_steps`, off the default path because most accounts do not have it.

anything claiming "sign in with aws" and then asking for a key is storing a durable credential. this module does not.

## request specs, not vibes

every provider call is built as a spec (method, url, headers, body) so tests can assert it offline, and `cloud_machine` is **dry by default**: with no token in the vault it returns the exact calls it would make, and only executes when a credential exists. the card shows the plan before anything is created.

the aws signer is hand-rolled (`cloud.sigv4`, no boto3 dependency) and **cross-checked against botocore**: for the same request and timestamp, our `Authorization` header is byte-identical to `boto3`'s. a wrong signer reads exactly like a permissions bug, so it is pinned by test.

## what is verified and what is not

`PROVIDERS[*]['verified']` is `False` for all three, and the gui shows it. verified means: an owner connected with their own account and a machine booted. until that happens the honest status is "request shapes built, signer matched to botocore, no live call made". the endpoints, the auth lanes, the signer and the plans are tested here; the live account is not.

## the gap that matters next

the machines this lane creates boot the **provider's stock ubuntu** and get provisioned over ssh. our own qcow2 guests are not in azure's vhd or aws's ami format yet, so "your image, in the cloud" is the next work item: qcow2 → raw → vhd/ami import, plus the guest-side pieces (virtio drivers, cloud-init replacing our first-boot) that make our images bootable there.

## surface

- `GET /api/cloud/providers` - the three, with docker_needed, connected and verified
- `POST /api/cloud/connect` - `{provider, client_id, project?, tenant?, role_arn?, sso_start_url?}` → connect plan (device code, pkce url, or federation template)
- `POST /api/cloud/complete` - `{provider, token}` → stored in the vault as `cloud:<provider>`, never logged
- `POST /api/cloud/machines` - machine calls, dry unless connected
