# giulia-cli

> **Status: planned**

Command-line interface for the `giulia` agent framework.

---

## Planned commands

```
giulia doctor               # verify installation and layer health (like nest doctor)
giulia run <agent>          # start a local agent from a config.yaml
giulia deploy <agent>       # package and deploy to a target environment
giulia register <agent>     # manually register an agent in the registry
giulia scenarios list       # list available agent scenarios / templates
giulia scenarios cp <name>  # copy a template agent to the current directory
```

## Installation (future)

```bash
pip install "giulia[cli]"
```

Or via the workspace:

```bash
uv sync
uv run giulia --help
```

## Contributing

See the root [CONTRIBUTING.md](../../CONTRIBUTING.md) and the workspace
[Makefile](../../Makefile) for development setup.
