from GraphQlScripts.BasicFunctionalities import *
import datetime



from GraphQlScripts.Keys import API_KEY
API_URL = "https://api-op.grid.gg/central-data/graphql"
STATS_URL="https://api-op.grid.gg/stats-feed/graphql"
GAME_ID = "6" #Valorant game ID. Don't want LOL Data

transport = RequestsHTTPTransport(
    url=API_URL,
    headers={"x-api-key": API_KEY},
    verify=True,
    retries=2,
)

client = Client(transport=transport, fetch_schema_from_transport=True)


def getTeams() -> Dict[str, Any]:
    query = gql(
        """
        query GetTeams {
          teams(filter: { titleId: "6" }, first: 50) {
            totalCount
            pageInfo {
              hasPreviousPage
              hasNextPage
              startCursor
              endCursor
            }
            edges {
              cursor
              node {
                ...teamFields
              }
            }
          }
        }

        fragment teamFields on Team {
          id
          name
          colorPrimary
          colorSecondary
          logoUrl
          externalLinks {
            dataProvider {
              name
            }
            externalEntity {
              id
            }
          }
        }
        """
    )
    result = client.execute(query)
    writeToJSON(result, "teamData.json")
    return result


def getTeamId(team_name:str)-> Dict[str,Any]:
    team_lookup = gql(
        """
        query GetTeamId($teamFilter: TeamFilter!) {
          teams(filter: $teamFilter, first: 1) {
            edges {
              node {
                id
                name
              }
            }
          }
        }
        """
    )
    team_filter = {
        "titleId": GAME_ID,
        "name": {"contains": team_name},
    }
    lookup_result = client.execute(team_lookup, variable_values={"teamFilter": team_filter})
    edges = lookup_result.get("teams", {}).get("edges", [])
    if not edges:
        raise ValueError(f"No team found matching '{team_name}' for title {GAME_ID}.")
    team_id = edges[0]["node"]["id"]
    return team_id



def getTeamPlayers(team_name: str) -> Dict[str, Any]:
    team_id=getTeamId(team_name)
    roster_query = gql(
        """
        query GetTeamRoster($playerFilter: PlayerFilter!) {
          players(filter: $playerFilter) {
            edges {
              node {
                id
                nickname
                title {
                  name
                }
                team {
                  name
                }
              }
            }
            pageInfo {
              hasNextPage
              hasPreviousPage
            }
          }
        }
        """
    )
    player_filter = {
        "titleId": GAME_ID,
        "teamIdFilter": {"id": team_id},
    }
    roster_result = client.execute(roster_query, variable_values={"playerFilter": player_filter})
    filename = f"{team_name}_players.json".replace(" ", "_")
    writeToJSON(roster_result, filename)
    return roster_result


def getPlayer(playerName: str, operator: str = "contains") -> Dict[str, Any]:
    allowed_ops = {
        "contains",
        "startsWith",
        "endsWith",
        "equalTo",
        "notEqualTo",
    }
    if operator not in allowed_ops:
        raise ValueError(f"Unsupported operator '{operator}'. Choose one of {sorted(allowed_ops)}.")
    nickname_filter = {operator: playerName}
    player_filter = {
        "nickname": nickname_filter,
        "titleId": GAME_ID,
    }
    query = gql(
        """
        query GetPlayers($playerFilter: PlayerFilter) {
          players(filter: $playerFilter) {
            edges {
              node {
                ...playerFields
              }
            }
          }
        }

        fragment playerFields on Player {
          id
          nickname
          title {
            name
          }
        }
        """
    )
    result = client.execute(query, variable_values={"playerFilter": player_filter})
    writeToJSON(result, "PlayerData.json")
    return result

def getPlayerInfo(player_id: str) -> Dict[str, Any]:
    query = gql(
        """
        query PlayerInfo($playerId: ID!) {
          player(id: $playerId) {
            id
            nickname
            roles {
              id
              name
              title {
                name
              }
            }
          }
        }
        """
    )
    result = client.execute(query, variable_values={"playerId": player_id})
    player = result.get("player")
    if not player:
        raise ValueError(f"No player found with ID '{player_id}'.")
    nickname = player.get("nickname") or player.get("fullName") or f"player_{player_id}"
    filename = f"{nickname}_info.json".replace(" ", "_")
    writeToJSON(result, filename)
    return result

def getTeamSeries(teamID: str) -> Dict[str, Any]:
    now_utc = datetime.datetime.utcnow()
    current_day = now_utc.replace(microsecond=0).isoformat() + "Z"
    one_year_ago = (now_utc - datetime.timedelta(days=365)).replace(microsecond=0).isoformat() + "Z"
    query = gql(
        """
        query Series($teamID: ID!, $after: String, $currentDay: String!, $oneYearAgo: String!) {
          allSeries(
            filter: {
              teamIds: { in: [$teamID] }
              startTimeScheduled: { gte: $oneYearAgo, lte: $currentDay }
            }
            first: 50
            after: $after
          ) {
            totalCount
            pageInfo {
              endCursor
              hasNextPage
            }
            edges {
              node {
                id
              }
            }
          }
        }
        """
    )
    all_edges: list = []
    total_count: int | None = None
    has_next = True
    cursor = None
    while has_next:
        result = client.execute(
            query,
            variable_values={
                "teamID": teamID,
                "after": cursor,
                "currentDay": current_day,
                "oneYearAgo": one_year_ago,
            },
        )
        series = result.get("allSeries")
        if not series:
            raise ValueError(f"No series found for team ID '{teamID}'.")
        if total_count is None:
            total_count = series.get("totalCount")
        page_info = series.get("pageInfo", {}) or {}
        all_edges.extend(series.get("edges", []) or [])
        has_next = bool(page_info.get("hasNextPage"))
        cursor = page_info.get("endCursor")
        if not cursor and has_next:
            break

    merged = {
        "allSeries": {
            "totalCount": total_count if total_count is not None else len(all_edges),
            "pageInfo": {
                "endCursor": cursor,
                "hasNextPage": has_next,
            },
            "edges": all_edges,
        }
    }
    filename = f"{teamID}_series.json".replace(" ", "_")
    writeToJSON(merged, filename)
    return merged

