# fab at jlcpcb: two revisions, both orderable

the owner's house is jlcpcb, so the board has to be designed for its constraints rather than adapted to them. two of those constraints shape the whole design:

1. **assembly parts come from the lcsc catalogue.** that decides where the euicc goes: an mff2 esim chip is not an off-the-shelf lcsc line, so a board whose assembly depends on it cannot be assembled cheaply. a nano-sim socket *is* in the catalogue, and so is an m.2 or mini-pcie connector.
2. **the cheap process tier is 4 layers, 5/5 mil, 0.3 mm drills.** fine for everything here except the rf feed, and even that is fine if the antenna lead is short and the module's own connector is used.

so: rev a proves the whole chain with parts that assemble in one click, rev b adds silicon we have to place ourselves.

## rev a: all-lcsc, socketed, no mff2

purpose: prove provisioning end to end on hardware that arrives assembled, and get a real number working in a modem.

| block | part strategy | note |
|---|---|---|
| module socket | mini-pcie 52-pin or m.2 key b, whichever the module family uses | socketed so the radio is swappable and the board is not scrap when a module dies |
| sim | nano-sim socket, plus a second socket behind a mux | holds a carrier prepaid sim, or an esim.me-style card for esim bring-up |
| power | 5 v usb-c in, 3.8 v buck for vbat, bulk caps at the module | lte tx bursts pull amps: wide copper, 470 uf+ close to the connector |
| per-port switch | tps2051b / ap2553 class load switch, one per port | the hard reset that saves a wedged modem without rebooting a host |
| keeper | rp2040 + w25q16 flash + usb-c | in the catalogue, cheap, and the firmware is ours |
| antenna | u.fl connectors, certified antenna from the module vendor | do not invent an antenna: this is the usual certification failure |
| usb to the host | usb 2.0 hs, 90 ohm differential | impedance control is a jlc option on 4-layer; keep the pair short and matched |

rev a does not need mff2 at all, because a nano-sim socket plus a removable euicc gets the same apdu path. that is the point: buy the bring-up board before the product board.

## rev b: the mff2 that makes it a product

rev b replaces the second socket with a soldered euicc (st4sim-200m for sgp.22, st4sim-300m for sgp.32). two honest options for getting it onto the board:

- **leave the footprint dnP in the jlc order and hot-air it yourself.** an mff2 is a large-pad lga with a clear land pattern; a stencil, paste and a hot-air station handle it, and the datasheet's land pattern is the whole spec. this keeps jlc for everything else.
- **use a turnkey assembler for the final board** and treat jlc as the prototype house. cheaper than fighting a catalogue.

either way, put the mff2 land pattern on rev a as well, unpopulated. the difference between rev a and rev b then becomes a part, not a redesign, which is the whole reason rev a exists.

## what jlc will not do for you

- **no rf tuning or certification.** impedance-controlled traces are an option, an antenna is not. use the module's certified antenna and its integration manual.
- **no functional test beyond what you design.** add test points on vbat, usb dp/dm, sim clk/io/rst and the keeper's uart: bring-up debugging on a 4-layer board without test points is a bad afternoon.
- **not a place for last-minute part swaps.** check stock and the basic/extended class before ordering; an extended part adds a per-part loading fee and can vanish from stock between revisions.
- **no consigned parts in standard smt.** plan around the catalogue, or hand-place.

## cost shape

five assembled rev a boards land in the low hundreds of dollars including the loading fees, before modules and antennas. modules and euicc silicon are the expensive line items and they move with the market, so price them at order time rather than in a spec that ages.

## keep in mind

the point of the board is not the board. it is a line that receives sms while a guest sleeps. rev a with a prepaid sim and a keeper proves that in an afternoon, and it needs neither esim nor mff2 to do it.
