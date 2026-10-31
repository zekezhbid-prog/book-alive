import { createContext, useContext } from 'react'

/** What the left menu of a project needs from the signed-in session. */
export const SessionActions = createContext<{ accounts: boolean; email: string; logout: () => void }>({
  accounts: false,
  email: '',
  logout: () => {},
})
export const useSessionActions = () => useContext(SessionActions)
