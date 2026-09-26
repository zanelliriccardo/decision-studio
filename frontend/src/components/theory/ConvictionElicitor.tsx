import { useState } from 'react'
import { useT } from '../../i18n/index.tsx'
import {
  LOTTERY_STEPS,
  answerLottery,
  describeLottery,
  lotteryEstimate,
  lotteryProbe,
  startLottery,
  type LotteryChoice,
} from '../../lib/theoryValue.ts'

const pct = (p: number) => `${Math.round(p * 100)}%`

/**
 * Elicit a conviction by comparing bets, not by asking for a number.
 *
 * Each question offers the same prize two ways: if the theory holds, or on a
 * draw with a stated chance. Which one someone would rather take brackets
 * their belief, and four answers narrow it to a few percent.
 */
export default function ConvictionElicitor({
  onDone,
  onCancel,
}: {
  onDone: (value: number, note: string) => void
  onCancel: () => void
}) {
  const { t } = useT()
  const [state, setState] = useState(startLottery)
  const choose = (choice: LotteryChoice) => setState((s) => answerLottery(s, choice))
  const probe = lotteryProbe(state)

  if (state.done) {
    const value = lotteryEstimate(state)
    return (
      <div className="space-y-2" data-testid="conviction-elicitor">
        <p className="text-[11px] text-text-secondary">
          {t.theoryValue.lotteryResult.replace('{p}', pct(value))}
        </p>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => onDone(value, `lottery: ${describeLottery(state)}`)}
            className="px-2.5 py-1 text-[11px] rounded-md bg-ocean-500/15 text-ocean-300 border border-ocean-500/30 hover:bg-ocean-500/25"
          >
            {t.theoryValue.save}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="px-2.5 py-1 text-[11px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600"
          >
            {t.theoryValue.cancel}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-1.5" data-testid="conviction-elicitor">
      <p className="text-[10px] text-text-muted">
        {t.theoryValue.lotteryStep
          .replace('{n}', String(state.answers.length + 1))
          .replace('{total}', String(LOTTERY_STEPS))}
      </p>
      <p className="text-[11px] text-text-primary">{t.theoryValue.lotteryQuestion}</p>
      <div className="grid grid-cols-2 gap-1.5">
        <button
          type="button"
          onClick={() => choose('theory')}
          className="px-2 py-1.5 text-[11px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 text-left"
        >
          {t.theoryValue.lotteryTheory}
        </button>
        <button
          type="button"
          onClick={() => choose('draw')}
          className="px-2 py-1.5 text-[11px] rounded-md bg-surface-700 text-text-secondary border border-surface-600 hover:bg-surface-600 text-left"
        >
          {t.theoryValue.lotteryDraw.replace('{p}', pct(probe))}
        </button>
      </div>
      <div className="flex gap-1.5">
        <button
          type="button"
          onClick={() => choose('same')}
          className="px-2 py-1 text-[10px] rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-700"
        >
          {t.theoryValue.lotterySame}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="px-2 py-1 text-[10px] rounded-md text-text-muted hover:text-text-secondary hover:bg-surface-700"
        >
          {t.theoryValue.cancel}
        </button>
      </div>
    </div>
  )
}
