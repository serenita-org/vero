# Docker

The recommended way to run Vero is to use a stable release version of the official Docker image:

```bash
docker run ghcr.io/serenita-org/vero:<version> <arguments>
```

For example:
```bash
docker run ghcr.io/serenita-org/vero:v1.2.0 --network=hoodi --remote-signer-url=http://signer:9000 --beacon-node-urls=http://lodestar:5052 --fee-recipient=0x0000000000000000000000000000000000000000
```

You can build Vero's image yourself using the included
[Dockerfile](https://github.com/serenita-org/vero/blob/master/Dockerfile){:target="_blank"}.

Take a look at the
[example docker compose file](https://github.com/serenita-org/vero/blob/master/compose-example.yaml){:target="_blank"}
or the [CLI reference](../../reference/cli_reference.md){:target="_blank"}
to find out what arguments Vero expects.

## eth-docker

You can also run Vero through the popular [eth-docker](https://ethdocker.com/){:target="_blank"} project.
A multi-client Vero-powered setup is described
[in the eth-docker docs](https://ethdocker.com/Usage/Advanced/Vero){:target="_blank"}.

eth-docker handles many setup tasks for you, including configuring
the remote signer Vero needs. It also makes importing your keys
into the remote signer easy.
