# heating-web

Web service for the heating system: a read-only API and the web interface it serves. It reads redis and never writes to it.

It is deployed and versioned on its own, apart from the control service in `boiler-relay`. The two share only the redis keys listed in `docs/redis-contract.md` of the parent repo, `GJMontreal/heating-system`.

Status: the first commit. The API still lives in `boiler-relay/api/` and moves here next.
