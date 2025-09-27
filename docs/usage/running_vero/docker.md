# Docker

The recommended way to run Vero is using a stable release version of the official image:

```bash
docker run ghcr.io/serenita-org/vero:<version> <arguments>
```

You can build Vero's image yourself using the included
[Dockerfile](https://github.com/serenita-org/vero/blob/master/Dockerfile).

Take a look at the
[example docker compose file](https://github.com/serenita-org/vero/blob/master/compose-example.yaml)
or the [CLI reference](../../reference/cli_reference.md)
to find out what arguments Vero expects.

## eth-docker

You can also run Vero through the popular [eth-docker](https://ethdocker.com/) project.
A multi-client Vero-powered setup is described
[in the eth-docker docs](https://ethdocker.com/Usage/Advanced/Vero).

eth-docker takes care of a lot of things for you, like setting up
the remote signer Vero needs. It also makes importing your keys
into the remote signer easy.
