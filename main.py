import json
from typing import Any, Dict

from gql import Client, gql
from gql.transport.requests import RequestsHTTPTransport

from Keys import API_KEY
API_URL = "https://api-op.grid.gg/central-data/graphql"
GAME_ID = "6"

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

def getTeamPlayers(team_name: str) -> Dict[str, Any]:
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


def writeToJSON(result: Dict[str, Any], filename: str) -> None:
    with open(filename, "w", encoding="utf-8") as team_file:
        json.dump(result, team_file, indent=2, ensure_ascii=False)
    print(f"Results written to {filename}")


if __name__ == "__main__":
    getTeamPlayers("Cloud9")
