# byollm: bring your own llm

the model is yours too. the control plane is model-blind: it never calls
an llm, never ships one, and never needs to know which one powers an
agent. whatever model drives your agent (a cloud api, local weights,
claude code, cursor, anything mcp) sees the same machines the web ui
provisions, over the same [agent bridge](../byoa/readme.md).

that is the trifecta: byoc (where machines run), byoa (who drives
them), byollm (who thinks). spawnables holds none of the three and
controls none of the three - it is the control plane in the middle, and
that is the product.
