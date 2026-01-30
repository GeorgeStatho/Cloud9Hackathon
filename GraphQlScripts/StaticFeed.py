from GraphQlScripts.BasicFunctionalities import *

from GraphQlScripts.Keys import API_KEY

API_URL = "https://api-op.grid.gg/statistics-feed/graphql"
GAME_ID = "6"  # Valorant game ID. Don't want LOL Data

transport = RequestsHTTPTransport(
    url=API_URL,
    headers={"x-api-key": API_KEY},
    verify=True,
    retries=2,
)

client = Client(transport=transport, fetch_schema_from_transport=True)


def GetTeamStats(team_id: str):
    query = gql(
        """
        query TeamStatisticsForLastThreeMonths($teamId: ID!) {
                teamStatistics(teamId: $teamId,filter: {
                timeWindow: LAST_3_MONTHS
                }) {
            id
            aggregationSeriesIds
            series {
              count
              kills {
                sum
                min
                max
                avg
              }
            }
            game {
              count
              wins {
                value
                count
                percentage
                streak {
                  min
                  max
                  current
                }
              }
            }
            segment {
              type
              count
              deaths {
                sum
                min
                max
                avg
              }
            }
          }
        }
        """
    )
    filter_input = {
        "timeWindow": "LAST_3_MONTHS",
    }
    stats_result = client.execute(
        query, variable_values={"teamId": team_id, "filter": filter_input}
    )
    filename = f"{team_id}_teamstats.json".replace(" ", "_")
    writeToJSON(stats_result, filename)
    return stats_result

def getPlayerStats(playerID:str):
    query=gql("""
    query PlayerStatisticsForLastThreeMonths($playerID: ID!) {
      playerStatistics(
        playerId: $playerID
        filter: { timeWindow: LAST_3_MONTHS }
      ) {
        id
        aggregationSeriesIds

        series {
          __typename

          ... on ValorantPlayerSeriesStatistics {
            count

            kills  { sum min max avg }
            deaths { sum min max avg }

            # often "won" is the win-rate object in this API
            won {
              value
              count
              percentage
              streak { min max current }
            }

            firstKill { value count percentage }

            killAssistsGiven { sum min max avg }
            killAssistsReceived { sum min max avg }

            teamkills { sum min max avg }
          }
        }
      }
    }
    """)
    stats_result = client.execute(query, variable_values={"playerID": playerID})
    filename = f"{playerID}_playerstats.json".replace(" ", "_")
    writeToJSON(stats_result, filename)
    return stats_result
getPlayerStats("3259")

