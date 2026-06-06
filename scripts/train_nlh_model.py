import os
import torch
import rlcard
from rlcard.agents import DQNAgent
from rlcard.utils import (
    get_device,
    set_seed,
    Logger,
)

def train(save_path="data/models/nlh_dqn.pth", episodes_per_count=2000):
    device = get_device()
    set_seed(42)
    
    # 3. 初始化全局 DQN 代理 (共享模型)
    # 不管多少玩家，状态空间始终是 54 维，动作空间 5 维
    agent = DQNAgent(
        num_actions=5,
        state_shape=[54],
        mlp_layers=[512, 512],
        device=device,
    )

    log_dir = "logs/training_log"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    print(f"开始跨人数训练计划 (2-9 玩家)... 每组训练 {episodes_per_count} 回合。")

    with Logger(log_dir) as logger:
        # 遍历 2 到 9 个玩家的对局场景
        for num_players in range(2, 10):
            print(f"\n[PHASE] 正在训练 {num_players} 玩家模式...")
            
            # 重新创建环境
            env = rlcard.make('no-limit-holdem', config={
                'game_num_players': num_players,
                'seed': 42
            })
            
            # 设置所有座位的玩家都使用同一个代理进行自对弈
            env.set_agents([agent for _ in range(num_players)])

            for episode in range(episodes_per_count):
                trajectories, payoffs = env.run(is_training=True)
                
                # 记录第一席位的收益作为指标
                if episode % 100 == 0:
                    logger.log_performance(
                        (num_players - 2) * episodes_per_count + episode, 
                        payoffs[0]
                    )

    # 5. 保存模型
    if not os.path.exists(os.path.dirname(save_path)):
        os.makedirs(os.path.dirname(save_path))
    
    torch.save(agent.q_estimator.qnet.state_dict(), save_path)
    print(f"\n训练完成！多人数模型已保存至: {save_path}")

if __name__ == "__main__":
    # 总共训练 8 组人数 * 2000 = 16000 回合
    train(episodes_per_count=2000)
