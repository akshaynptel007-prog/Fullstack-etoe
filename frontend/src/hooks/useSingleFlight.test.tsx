import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { useSingleFlight } from './useSingleFlight'

function Harness({ action }: { action: () => Promise<void> }) {
  const run = useSingleFlight(action)
  return <button onClick={() => void run()}>buy</button>
}

describe('useSingleFlight', () => {
  it('fires exactly one request for a burst of rapid clicks', async () => {
    let release!: () => void
    const action = vi.fn(() => new Promise<void>((resolve) => (release = resolve)))
    const user = userEvent.setup()
    render(<Harness action={action} />)

    const button = screen.getByRole('button')
    await user.tripleClick(button)
    await user.click(button)
    expect(action).toHaveBeenCalledTimes(1)

    release()
    await vi.waitFor(() => expect(action).toHaveBeenCalledTimes(1))
    await user.click(button) // unlocked once the first run finished
    expect(action).toHaveBeenCalledTimes(2)
  })
})
