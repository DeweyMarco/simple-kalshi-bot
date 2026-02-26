"""Configuration constants for the genetic algorithm trading system."""

from pathlib import Path

# --- Population ---
POPULATION_SIZE = 100
INITIAL_BANKROLL = 100.0  # USD per bot per generation

# --- Timing ---
GENERATION_DURATION_SECONDS = 24 * 3600  # 24 hours
TICK_INTERVAL_SECONDS = 30  # How often bots evaluate markets
CHECKPOINT_INTERVAL_TICKS = 120  # Save checkpoint every ~1 hour
PROGRESS_LOG_INTERVAL_TICKS = 60  # Log progress every ~30 min

# --- Evolution ---
ELITE_COUNT = 5  # Top N survive unchanged
TOURNAMENT_SIZE = 7  # Tournament selection pressure
CROSSOVER_RATE = 0.7  # Probability of crossover vs clone
MUTATION_RATE = 0.15  # Per-gene mutation probability
MUTATION_SIGMA = 0.10  # Gaussian stddev for gene perturbation
IMMIGRATION_COUNT = 5  # Random new genomes each generation

# --- Fitness ---
MIN_SETTLED_TRADES = 5  # Minimum trades to qualify for positive fitness
INACTIVE_FITNESS_PENALTY = -100.0  # Fitness for bots with too few trades

# --- Market Data ---
MARKET_CLOSE_WINDOW_HOURS = 24  # Only fetch markets closing within this window
MARKET_HISTORY_MAX_TICKS = 120  # Rolling price history per market (~60 min at 30s)

# --- Settlement ---
SETTLEMENT_WAIT_HOURS = 4  # Hours to wait after trading for markets to settle
SETTLEMENT_CHECK_TICKS = 10  # Targeted settlement check every N ticks (~5 min)
SETTLEMENT_WAIT_POLL_SECONDS = 120  # Poll interval during settlement wait

# --- Persistence ---
STATE_DIR = Path("data/evolution")
