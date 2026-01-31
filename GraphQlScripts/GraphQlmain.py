import os

from CentralData import getTeamId, getTeamSeries, getTeamPlayers
from FileDownload import download_series_files, download_file
from BasicFunctionalities import *

def generatePlayersFromTeamName(teamName: str) -> Dict[str, Any]:
        players = getTeamPlayers(teamName)
        player_map: Dict[str, Any] = {}
        for player in players.get("players", {}).get("edges", []):
                node = player.get("node", {})
                nickname = node.get("nickname")
                player_id = node.get("id")
                if nickname and player_id:
                        player_map[nickname] = player_id
        safe_team = teamName.replace(" ", "_")
        team_dir = os.path.join("Data", safe_team)
        os.makedirs(team_dir, exist_ok=True)
        filename = os.path.join(safe_team, f"{safe_team}_players.json")
        writeToJSON(player_map, filename)
        return player_map

def generateTeamSeriesFiles(teamName: str, max_files: int | None = None):
        teamId = getTeamId(teamName)
        teamSeries = getTeamSeries(teamId)
        base_dir = os.path.join("Data", teamName, "series")
        downloaded = 0
        for series in teamSeries["allSeries"]["edges"]:
                series_files = download_series_files(series["node"]["id"]).get("files", [])
                for entry in series_files:
                        if max_files is not None and downloaded >= max_files:
                                return
                        file_name = entry["fileName"]
                        output_path = os.path.join(base_dir, file_name)
                        download_file(entry["fullURL"], file_name, output_path=output_path)
                        downloaded += 1

generateTeamSeriesFiles("NRG", 30)
        
                
