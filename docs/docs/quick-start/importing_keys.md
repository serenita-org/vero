# Importing keys

!!! danger

    Running validator keys in two different places will result
    in slashing. Before continuing, make absolutely
    sure your validator keys are not active anywhere else.

    If you have previously used these validator keys elsewhere,
    either export and import their slashing protection data,
    or ensure the validators have been offline for at least
    two finalized epochs.

Place your validator keystores in the `vero/.eth/validator_keys`
directory.

Then run the `./ethd keys import` command and follow the instructions.
After the keys are imported, restart Vero using `./ethd restart validator`.
Vero will then begin performing duties for your validators.

When Vero starts successfully, its logs will include lines like:

```
INFO : Initialized beacon node at http://...
INFO : Updating duties
INFO : Started validator duty services
INFO : Subscribing to events
```
