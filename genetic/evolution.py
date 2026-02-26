"""Evolution mechanics: selection, crossover, mutation."""

from __future__ import annotations

import copy
import random
from typing import TYPE_CHECKING

from genetic.config import (
    CROSSOVER_RATE,
    ELITE_COUNT,
    IMMIGRATION_COUNT,
    INACTIVE_FITNESS_PENALTY,
    MIN_SETTLED_TRADES,
    MUTATION_RATE,
    MUTATION_SIGMA,
    POPULATION_SIZE,
    TOURNAMENT_SIZE,
)
from genetic.genome import Genome

if TYPE_CHECKING:
    from genetic.bot import GeneticBot


def evaluate_fitness(bot: GeneticBot) -> float:
    """
    Fitness = ROI (%).
    Bots with fewer than MIN_SETTLED_TRADES get a large penalty.
    """
    acct = bot.account
    if acct.n_settled < MIN_SETTLED_TRADES:
        return INACTIVE_FITNESS_PENALTY
    return acct.roi_pct


def select_parent(population: list[GeneticBot]) -> GeneticBot:
    """Tournament selection: pick TOURNAMENT_SIZE random bots, return best."""
    candidates = random.sample(population, min(TOURNAMENT_SIZE, len(population)))
    return max(candidates, key=evaluate_fitness)


def crossover(parent_a: Genome, parent_b: Genome, gen_num: int) -> Genome:
    """Uniform crossover: for each gene, randomly pick from parent A or B."""
    child = Genome(
        generation=gen_num,
        parent_ids=[parent_a.id, parent_b.id],
    )
    for gene_name in Genome.gene_names():
        if random.random() < 0.5:
            setattr(child, gene_name, getattr(parent_a, gene_name))
        else:
            setattr(child, gene_name, getattr(parent_b, gene_name))
    return child


def mutate(genome: Genome) -> Genome:
    """
    Gaussian mutation: each gene has MUTATION_RATE chance of being
    perturbed by N(0, MUTATION_SIGMA), clamped to [0, 1].
    """
    g = copy.deepcopy(genome)
    for gene_name in Genome.gene_names():
        if random.random() < MUTATION_RATE:
            old_val = getattr(g, gene_name)
            delta = random.gauss(0, MUTATION_SIGMA)
            new_val = max(0.0, min(1.0, old_val + delta))
            setattr(g, gene_name, new_val)
    return g


def evolve(population: list[GeneticBot]) -> list[Genome]:
    """
    Produce the next generation of genomes from the current population.

    1. Sort by fitness
    2. Keep top ELITE_COUNT unchanged
    3. Fill remaining slots via tournament selection + crossover/mutation
    4. Add IMMIGRATION_COUNT random genomes for diversity
    """
    ranked = sorted(population, key=evaluate_fitness, reverse=True)
    gen_num = ranked[0].genome.generation + 1
    next_gen: list[Genome] = []

    # 1. Elitism: keep top N unchanged
    for bot in ranked[:ELITE_COUNT]:
        elite = bot.genome.clone()
        elite.generation = gen_num
        elite.parent_ids = [bot.genome.id]
        next_gen.append(elite)

    # 2. Breed to fill
    breed_count = POPULATION_SIZE - ELITE_COUNT - IMMIGRATION_COUNT
    for _ in range(breed_count):
        parent_a = select_parent(population)
        if random.random() < CROSSOVER_RATE:
            parent_b = select_parent(population)
            child = crossover(parent_a.genome, parent_b.genome, gen_num)
        else:
            child = parent_a.genome.clone()
            child.generation = gen_num
            child.parent_ids = [parent_a.genome.id]

        child = mutate(child)
        next_gen.append(child)

    # 3. Immigration: random new genomes for diversity
    for _ in range(IMMIGRATION_COUNT):
        next_gen.append(Genome.random(generation=gen_num))

    return next_gen
