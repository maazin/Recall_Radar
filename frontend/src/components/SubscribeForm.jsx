import { useState } from 'react'
import { createSubscription } from '../api'

export default function SubscribeForm() {
  const [email, setEmail] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')
  const [keywordFilter, setKeywordFilter] = useState('')
  const [state, setState] = useState({ status: 'idle', message: '' })

  async function handleSubmit(event) {
    event.preventDefault()
    setState({ status: 'saving', message: '' })
    try {
      await createSubscription({ email, categoryFilter, keywordFilter })
      setState({
        status: 'done',
        message: 'Subscribed. You will be emailed when a newly published record matches.',
      })
      setEmail('')
      setKeywordFilter('')
    } catch (error) {
      setState({ status: 'error', message: error.message })
    }
  }

  return (
    <section className="subscribe" id="subscribe">
      <h2>Get notified</h2>
      <p className="subscribe__blurb">
        Enter an email and an optional brand or chain. When RecallRadar indexes a newly
        published agency record that matches, you&apos;ll get a message with a link to
        the original record.
      </p>

      <form onSubmit={handleSubmit} className="subscribe__form">
        <label>
          <span>Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </label>

        <label>
          <span>Category</span>
          <select value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
            <option value="">All</option>
            <option value="grocery">Grocery</option>
            <option value="restaurant">Restaurant</option>
          </select>
        </label>

        <label>
          <span>Brand or keyword (optional)</span>
          <input
            type="text"
            value={keywordFilter}
            onChange={(e) => setKeywordFilter(e.target.value)}
            placeholder="e.g. Chipotle, Listeria"
          />
        </label>

        <button type="submit" disabled={state.status === 'saving'}>
          {state.status === 'saving' ? 'Subscribing…' : 'Subscribe'}
        </button>
      </form>

      {state.message && (
        <p className={`subscribe__message subscribe__message--${state.status}`} role="status">
          {state.message}
        </p>
      )}
    </section>
  )
}
