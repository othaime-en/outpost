/**
 * Team-scoped permission helpers
 *
 * IMPORTANT CAVEAT — staleness: these helpers read off the `User` object
 * from AuthContext, which is only refreshed on login. If the CURRENT user's
 * own memberships change during the session (e.g. they just self-serve
 * created a team, or just left one), AuthContext's cached copy is stale
 * until next login. For exactly that reason, pages that mutate the current
 * user's own membership (Teams.tsx, TeamDetail.tsx) deliberately do NOT use
 * these helpers to gate their own UI — they derive permissions from
 * freshly-fetched data instead (e.g. TeamDetail reads the caller's role out
 * of the team detail response's own `members` list, which is refetched on
 * every load). These helpers remain safe to use for read-only scoping
 * decisions (e.g. "should I show a team filter dropdown") where a session's
 * worth of staleness has no real consequence.
 */

import type { TeamRole, User } from '../api/client'

export function isSuperAdmin(user: User | null): boolean {
  return user?.platform_role === 'super_admin'
}

/** This user's role on one specific team, or null if they have no
 * membership there. Does not account for super_admin — see hasTeamRole. */
export function teamRole(user: User | null, teamId: string): TeamRole | null {
  if (!user) return null
  const m = user.team_memberships.find((m) => m.team_id === teamId)
  return m ? m.role : null
}

/**
 * True if the user qualifies for one of `roles` on this team. super_admin
 * always qualifies. Called with no `roles`, checks for any membership at
 * all (i.e. "can this user see this team").
 */
export function hasTeamRole(user: User | null, teamId: string, ...roles: TeamRole[]): boolean {
  if (isSuperAdmin(user)) return true
  const role = teamRole(user, teamId)
  if (roles.length === 0) return role !== null
  return role !== null && roles.includes(role)
}