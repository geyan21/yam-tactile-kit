# YAM integration context from the original workspace

The original workspace documented YAM deployment through a policy server and a robot-owning client, with visual observations, robot state, and gripper actions. The design review did not find an implemented tactile interface in that documented contract.

The kit proposes adding timestamped tactile acquisition and recording, a separate calibrated force signal for each jaw, and a bounded local feedback layer. It does not include or change the original policy, trained checkpoints, robot drivers, or steering experiments.

The actual YAM actuator variant and control interface must be verified on the intended system. Published I2RT motor-effort force limiting is distinct from directly measuring finger contact force.

Primary robot reference: [I2RT YAM documentation](https://doc.i2rt.com/products/yam).
