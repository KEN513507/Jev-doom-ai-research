# controller_v2

新しいCLEAR用Controllerを、旧decision loopから分離して実装する領域。

最初の目標は新機能追加ではなく **Action ownership の一本化**。

参照:
- `docs/controller_v2/ARCHITECTURE_CONTRACT.md`
- `docs/controller_v2/SPRINT_PLAN.md`

旧コードから再利用してよいもの:
- ViZDoom I/O / adapter
- Action enum/vector mapping
- perception DTO
- Jev API client
- run/timeline logging

初期段階で移植しないもの:
- legacy decision loop
- direct action rewrite chain
- hidden side effects
- monolithic agent control
