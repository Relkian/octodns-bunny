## Bunny provider for octoDNS

An [octoDNS](https://github.com/octodns/octodns/) provider that targets [Bunny](https://bunny.net/dns/).

### Installation

#### Command line

```
pip install octodns-bunny
```

#### requirements.txt/setup.py

Pinning specific versions or SHAs is recommended to avoid unplanned upgrades.

##### Versions

```
# Start with the latest versions and don't just copy what's here
octodns==1.11.0
octodns-bunny==1.0.0
```

##### SHAs

```
# Start with the latest/specific versions and don't just copy what's here
-e git+https://git@github.com/octodns/octodns.git@42f8eef0b69957984f8d78b6dc4f106ff9e6ebaa#egg=octodns
-e git+https://git@github.com/octodns/octodns-bunny.git@cfc1d0ae4da41675d404e837e92e033da901c389#egg=octodns_bunny
```

### Configuration

```yaml
providers:
  bunny:
    class: octodns_bunny.BunnyProvider
    # Your Bunny API key (required)
    api_key: env/BUNNY_API_KEY
```

### Support Information

#### Records

This provider supports `A`, `AAAA`, `CAA`, `CNAME`, `MX`, `NS`, `PTR`, `SRV` and `TXT` records.

#### Dynamic

This provider does not support dynamic records.

### Development

See the [/script/](/script/) directory for some tools to help with the development process. They generally follow the [Script to rule them all](https://github.com/github/scripts-to-rule-them-all) pattern. Most useful is `./script/bootstrap` which will create a venv and install both the runtime and development related requirements. It will also hook up a pre-commit hook that covers most of what's run by CI.
