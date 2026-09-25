import { useT } from '../../i18n/index.tsx'
import type { NodeDivergenceStability } from '../../types/api.ts'

/**
 * Qualifies a scenario comparison with how much of it survived simulation.
 *
 * Both scenario scores come from weights a language model invented, so a
 * divergence that vanishes when those weights are perturbed is an artefact of
 * the noise rather than a difference between the scenarios. Reporting the raw
 * divergence count alone states such artefacts as findings.
 *
 * Renders nothing when the server did not compute stability, so older responses
 * degrade quietly instead of showing a misleading zero.
 */
export default function DivergenceStabilityBadge({
  stability,
  divergentCount,
  robustNodeIds,
  simulationRuns,
}: {
  stability?: NodeDivergenceStability[]
  divergentCount: number
  robustNodeIds?: string[]
  simulationRuns?: number
}) {
  const { t } = useT()

  if (!stability || stability.length === 0) return null

  const robustCount =
    robustNodeIds?.length ?? stability.filter((row) => row.robust).length
  const allHeld = robustCount === divergentCount

  return (
    <span
      className={`text-xs ${allHeld ? 'text-confidence-high' : 'text-amber-400'}`}
      title={t.comparison.robustHint.replace(
        '{runs}',
        String(simulationRuns ?? 0),
      )}
      data-testid="robust-divergence-count"
    >
      {t.comparison.robustDivergent
        .replace('{robust}', String(robustCount))
        .replace('{total}', String(divergentCount))}
    </span>
  )
}
