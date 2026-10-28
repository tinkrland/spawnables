# spawnables

agents keep getting handed a browser tab and a terminal, and every once in a while you notice how weird that is. spawnables is my attempt at the thing in between.

## the problem

right now there are basically two ways to give an agent a computer, and both are kind of limiting.

the first is the ephemeral sandbox. spin up a firecracker microvm, run the code, hand back stdout, throw it away. or the browser-automation lane: a real chrome somewhere, driven through the dom. both are turnkey, both are useful, and both are gone when the task ends. nothing persists, nothing accumulates, and the moment the work needs anything outside the terminal or the dom, the lane just stops existing.

the second is the dedicated agent computer. there are real services now that give your agent its own always-on machine with its own little life, and honestly some of them are nice. the catch is they only exist inside packaged agent saas. the computer is yours the way a hotel room is yours: you check in, you use it, you leave. you do not pick the infrastructure, you do not pick the agent, and you do not really control the machine.

## the point

spawnables is not reinventing the wheel. the wheel is [celesto](https://github.com/celestoai/celesto) (apache-2.0, open source) and it is a good wheel. what spawnables adds is the easy path to an agent having its own fixed computer that is actually under your control.

fixed, not ephemeral: a spawned machine stays. it accumulates files, logins, state, a personality. you pause it, you freeze it, it is there tomorrow.

yours, not rented: the machine runs on your infrastructure ([byoc](connect/byoc/readme.md): bare metal, a vps, gcp, aws, azure), driven by your agent ([byoa](connect/byoa/readme.md): cloud or local, any mcp client), with your model ([byollm](connect/byollm/readme.md)). spawnables holds no infrastructure, no agent, and no model of its own. the control plane is the product.

clean, not opinionated: no skills baked into the os, ever. the machine ships exactly what you ordered and nothing else.

that is the whole pitch: the byoc + byoa + byollm trifecta, and the machine is a card you can pause, freeze, thaw, duplicate, export, or burn.

## beyond linux, beyond the browser

to be fair, some sandbox options are open source and you can spin them up yourself. they are almost always linux sandboxes though. which is fine until the task is not a linux task.

a lot of real life runs through consumer apps that ship for windows, macos, android, or ios and never for linux. an agent living in a linux sandbox can only reach those through the browser, and the dom is exactly the part many of these apps do not have. spawnables is for when the work goes beyond the browser.

so instead of pretending one size fits all, you bring the tool for the specific task: a [mint desktop](spawnables/linux/readme.md) when the work is human-ish, a [windows box](spawnables/windows/readme.md) when the app is a windows app, a [macos machine](spawnables/macos/readme.md) on real apple silicon for the apple-only ones (and [ipad apps via playcover](spawnables/ipad/readme.md)), an [android phone or tablet](spawnables/android/readme.md) when the work lives in phone apps. you customize what you think fits, before you spawn it up, down to the distro, the desktop, the apps, the rice, the network story. and every card says honestly what it can and cannot do.

everything else lives in [directory.md](directory.md).
