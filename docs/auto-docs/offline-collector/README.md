# Offline Collector — Design Docs

Auto-generated from conversation on 2026-04-12/13. Each file captures one design output.

## Files

| # | File | Topic |
|---|------|-------|
| 01 | [E2E pipeline stages](01-e2e-pipeline-stages.md) | 7-stage verification map: app → queue → worker → archive |
| 02 | [How the collector works](02-collector-how-it-works.md) | Current collector.py: watermarks, dedup, direct/queue modes |
| 03 | [NAT worker strategies](03-nat-worker-strategies.md) | Combinatorial strategy grid for collecting from NAT'd workers |
| 04 | [Approach 1: Queue drain](04-approach1-queue-drain.md) | Polite backpressure — worker pushes through queue when idle |
| 05 | [Approach 2: TCP receiver](05-approach2-tcp-archive-receiver.md) | Dedicated TCP receiver on DO box, separate port, queue untouched |
| 06 | [TCP admission control protocol](06-tcp-receiver-admission-control-protocol.md) | Binary header + verdict + adaptive batch sizing + serialization options |
| 07 | [Local E2E deployment](07-e2e-local-deployment.md) | tmux setup, real Android app test, verification steps |
| 08 | [State diagram + archive receiver deployment](08-state-diagram-archive-receiver.md) | Full pipeline diagram, strict tmux naming, startup scripts |
