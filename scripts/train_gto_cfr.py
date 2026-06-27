#!/usr/bin/env python3
"""
GTO CFR训练脚本

用法:
    uv run python scripts/train_gto_cfr.py
    uv run python scripts/train_gto_cfr.py --algorithm mccfr --iterations 50000
    uv run python scripts/train_gto_cfr.py --deep
"""
import argparse
import logging
import os
import sys
import time
import yaml

# 确保项目根目录在sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.strategies.gto.solver import GTOSolver

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(project_root, "logs", "gto_training.log"), mode="a"),
    ],
)
logger = logging.getLogger("train_gto")


def load_config(config_path: str) -> dict:
    """加载训练配置"""
    if not os.path.exists(config_path):
        logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
        return {}

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def main():
    parser = argparse.ArgumentParser(description="GTO CFR训练脚本")
    parser.add_argument("--config", default="config/gto_training.yaml", help="训练配置文件")
    parser.add_argument("--algorithm", choices=["vanilla", "cfrplus", "mccfr"], help="CFR算法(覆盖配置)")
    parser.add_argument("--iterations", type=int, help="迭代次数(覆盖配置)")
    parser.add_argument("--deep", action="store_true", help="启用DeepCFR训练")
    parser.add_argument("--export-only", action="store_true", help="只从已有模型导出策略表")
    parser.add_argument("--resume", action="store_true", help="从已有模型继续训练")
    parser.add_argument("--flop-buckets", type=int, help="翻牌bucket数")
    parser.add_argument("--turn-buckets", type=int, help="转牌bucket数")
    parser.add_argument("--river-buckets", type=int, help="河牌bucket数")
    args = parser.parse_args()

    # 加载配置
    config = load_config(args.config)

    # 命令行参数覆盖配置
    algorithm = args.algorithm or config.get("algorithm", "mccfr")
    iterations = args.iterations or config.get("training", {}).get("iterations", 10000)

    card_cfg = config.get("card_abstraction", {})
    action_cfg = config.get("action_abstraction", {})
    game_cfg = config.get("game", {})
    output_cfg = config.get("output", {})

    flop_buckets = args.flop_buckets or card_cfg.get("flop_buckets", 10)
    turn_buckets = args.turn_buckets or card_cfg.get("turn_buckets", 10)
    river_buckets = args.river_buckets or card_cfg.get("river_buckets", 10)

    # 创建求解器
    solver = GTOSolver(
        algorithm=algorithm,
        flop_buckets=flop_buckets,
        turn_buckets=turn_buckets,
        river_buckets=river_buckets,
        action_sizes=action_cfg.get("sizes"),
        small_blind=game_cfg.get("small_blind", 1),
        big_blind=game_cfg.get("big_blind", 2),
        starting_stack=game_cfg.get("starting_stack", 100),
        num_opponents=game_cfg.get("num_opponents", 1),
    )

    # 恢复模型
    model_dir = output_cfg.get("model_dir", "data/gto")
    if args.resume or args.export_only:
        if not solver.load_model(model_dir):
            logger.error("模型加载失败，请先训练")
            sys.exit(1)

    # 只导出
    if args.export_only:
        tables_path = output_cfg.get("tables_path", "config/gto_tables.yaml")
        result_path = solver.export_tables(tables_path)
        logger.info(f"策略表已导出: {result_path}")
        return

    # 训练
    logger.info("=" * 60)
    logger.info(f"GTO CFR 训练")
    logger.info(f"  算法: {algorithm}")
    logger.info(f"  迭代: {iterations}")
    logger.info(f"  抽象: flop={flop_buckets}, turn={turn_buckets}, river={river_buckets}")
    logger.info("=" * 60)

    stats = solver.train(iterations)

    logger.info(f"训练统计: {stats}")

    # 保存模型
    solver.save_model(model_dir)

    # Deep CFR训练
    if args.deep:
        deep_cfg = config.get("training", {})
        deep_stats = solver.train_deep_cfr(
            iterations=deep_cfg.get("deep_iterations", 100),
            traversals=deep_cfg.get("deep_traversals", 100),
            buffer_size=deep_cfg.get("deep_buffer_size", 10000),
            batch_size=deep_cfg.get("deep_batch_size", 256),
        )
        logger.info(f"DeepCFR训练统计: {deep_stats}")
        solver.save_model(model_dir)

    # 导出策略表
    tables_path = output_cfg.get("tables_path", "config/gto_tables.yaml")
    result_path = solver.export_tables(tables_path)
    logger.info(f"策略表已导出: {result_path}")
    logger.info("训练完成！")


if __name__ == "__main__":
    main()
