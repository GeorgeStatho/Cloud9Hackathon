from GraphQlScripts.BasicFunctionalities import *

from GraphQlScripts.Keys import API_KEY

API_URL = "https://api.grid.gg/file-download/list/{seriesId}"
GAME_ID = "6"  # Valorant game ID. Don't want LOL Data

transport = RequestsHTTPTransport(
    url=API_URL,
    headers={"x-api-key": API_KEY},
    verify=True,
    retries=2,
)



client = Client(transport=transport, fetch_schema_from_transport=True)

def getTeamMapData(teamID:str):
    query= gql("""query GetKillsPerSeriesSegment($teamID: ID!) {
                seriesState(id:$teamID) {
                    valid
                    teams {
                    id
                    won
                    kills
                    players {
                        id
                        kills
                    }
                    }
                    games {
                    sequenceNumber
                    teams {
                        id
                        won
                        kills
                        players {
                        id
                        kills
                        }
                    }
                    segments {
                        sequenceNumber
                        teams {
                        id
                        won
                        kills
                        players {
                            id
                            kills
                        }
                        }
                    }
                    }
                }
                }
                """)
    stats_result = client.execute(
        query, variable_values={"teamID": teamID}
    )
    filename = f"{teamID}_teamstats.json".replace(" ", "_")
    writeToJSON(stats_result, filename)
    return stats_result

getTeamMapData("5")
