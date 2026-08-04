# Device Policy

## Default
All ordinary work runs on the Seeker: Telegram, scheduling, Android tools, wallets, API calls, small scripts and light data processing.

## PC
The PC is preferred only for sustained CPU/storage work: Docker builds, compilation, large PDF batches, large file transformations and persistent LAN services. A PC action requires an explicit PC request. Never wake or shut down the PC implicitly.

## RunPod
GPU builds, CUDA compilation and large-model inference belong on RunPod, not the Seeker or the small home PC.

## Routing rule
1. Explicit device request wins.
2. Security-sensitive or Android-local task stays on Seeker.
3. GPU/large-model task → RunPod.
4. Heavy CPU/storage task → PC, but only after explicit authorization.
5. Otherwise → Seeker.

## Efficiency
- Avoid network hops for light work.
- Batch file/data operations.
- Cache one fetch and process locally.
- Use the cheapest adequate model tier.
- Do not retry identical failed actions blindly.
