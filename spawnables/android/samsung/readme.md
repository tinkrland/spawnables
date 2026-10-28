# the samsung persona

[redroid-15-samsung](../../../catalog/base-images/redroid-15-samsung.json)
is a separate base image whose persona claims a galaxy model. it
exists because some apps' features are store- or vendor-gated: with the
play store and galaxy-store apks seeing a samsung device, those gates
open.

the honest ceiling, on the card too: one ui system features are absent
(an aosp build wearing a samsung model string). if an app hard-requires
one ui itself, this persona will not save it, and we say so before the
order, not after.
