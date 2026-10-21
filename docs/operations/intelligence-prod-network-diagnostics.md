# Production RSS transport diagnostics

The successful EID acquisition [39555815006](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/39555815006) used the same pinned HTTPS transport, dependency lock and Dockerfile as the failed Ahead-of-Print [39657766350](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/39657766350) and Outbreaks [39658703504](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/39658703504) attempts. Both failures reported `FEED_NETWORK_FAILED`, one acquisition attempt, no artifact and no downstream publication.

The saved failures do not retain the underlying exception, HTTP status or selected address. They cannot establish TLS, socket, timeout, address-family or HTTP-protocol causality. The successful and failed hosted runs used different runner image revisions, kernels and regions; those differences do not prove a cause. Earlier successful local bounded captures do not prove hosted connectivity.

The transport uses a default verified TLS context, the original hostname for SNI, and a validated pinned address. It deliberately does not use proxy environment variables. It validates all resolved addresses and connects once to the first address. This correction does not change that behavior, DNS selection, trust roots, TLS verification, request bounds, redirects, retries, source identity or retention.

Future failures retain only a closed diagnostic code:

| Failure type | Code |
| --- | --- |
| Socket timeout | `FEED_TIMEOUT` |
| TLS certificate verification | `FEED_TLS_VERIFICATION_FAILED` |
| Other TLS failure | `FEED_TLS_FAILED` |
| HTTP protocol failure, including disconnected/truncated responses | `FEED_HTTP_PROTOCOL_FAILED` |
| Connection refused | `FEED_CONNECTION_REFUSED` |
| Connection reset or broken pipe | `FEED_CONNECTION_RESET` |
| Network/host unreachable or unsupported address family | `FEED_NETWORK_UNREACHABLE` |
| Unclassified operating-system error | `FEED_NETWORK_FAILED` |

Raw exception messages and traceback chains are suppressed at this boundary; no URLs, addresses, headers, payloads or credentials are added to diagnostics. A TLS failure code never permits bypassing certificate verification. A timeout never permits an automatic retry. Each failure still closes the connection and follows the existing acquisition failure path.

This is diagnostic preparation, not a demonstrated connectivity repair. The historical cause remains unknown. No provider request is needed to test classification: mocked connection, request, header and body failures verify the codes, redaction, one connection/at-most-one request and closure. An actual future attempt still requires its applicable reviewed source, exact release, protected production approval and explicit request-budget allocation. The unconsumed final request from the original envelope is held; this change does not reallocate or execute it.

## Address-order correction after the diagnostic attempt

The later Outbreaks attempt [39667087795](https://github.com/Caraway-Labs/one-health-lyme-gap-atlas-data/actions/runs/39667087795) reported `FEED_NETWORK_UNREACHABLE`, one attempt and no artifact. This narrows the failure class, but does not identify the chosen address or prove IPv6 causality. Offline inspection found that deduplicating `getaddrinfo` results with a set discarded the platform's address preference before choosing the first candidate. Deduplication now preserves resolver order. It does not impose a new address-family preference, perform another lookup, try an alternate address, bypass validation of any candidate, or change verified TLS/SNI. Mock tests cover IPv4-first and IPv6-first results, duplicates, and a failure of the first pinned candidate without an alternative retry. No production request is performed by this correction; live acceptance remains separate.
