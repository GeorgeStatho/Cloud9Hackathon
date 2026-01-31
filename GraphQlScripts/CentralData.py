from BasicFunctionalities import *

from Keys import API_KEY
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

def getTeamSeries(teamID:str)->Dict[str,Any]:
    query = gql(
        """
        query Series($teamID: ID!) {
          allSeries(filter: { teamIds: { in: [$teamID] } }) {
           totalCount
           edges {
               node {
                   id
                   }
               }
              }
            }"""
    )
    result = client.execute(query, variable_values={"teamID": teamID})
    series = result.get("allSeries")
    if not series:
        raise ValueError(f"No series found for team ID '{teamID}'.")
    filename = f"{teamID}_series.json".replace(" ", "_")
    writeToJSON(result, filename)
    return result

