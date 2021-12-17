from __future__ import print_function

import configparser
import os.path
import datetime
import webbrowser
import googleapiclient
import pytz

from typing import List, Tuple
from datetime import timedelta
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from apiclient import errors
from enum import Enum

from Logging import Logging

'''

Tools to manipulate/retrieve Google Slide elements and Google Drive files.

'''


class GoogleAPITools:
    class DateFormatMode(Enum):
        # Specifies the string format outputted by getFormattedNextSundayDate()
        Full = 0
        Short = 1

    def __init__(self, type: str) -> None:
        # If modifying these scopes, delete the file token.json.
        self.scope = ['https://www.googleapis.com/auth/presentations',
                      'https://www.googleapis.com/auth/spreadsheets',
                      'https://www.googleapis.com/auth/drive']

        # The ID of the source slide.
        if not os.path.exists("Data/" + type + "SlideProperties.ini"):
            raise IOError(f"ERROR : {type}SlideProperties.ini config file cannot be found.")
        config = configparser.ConfigParser()
        config.read("Data/" + type + "SlideProperties.ini")
        self.sourceSlideID = config["SLIDE_PROPERTIES"][type + "SourceSlideID"]

        # Retrieve global configuration
        if not os.path.exists("Data/GlobalProperties.ini"):
            raise IOError(f"ERROR : GlobalProperties.ini config file cannot be found.")
        self.globalConfig = configparser.ConfigParser()
        self.globalConfig.read("Data/GlobalProperties.ini")

        # Get access to the slide, sheet, and drive
        [self.slideService, self.sheetService, self.driveService] = self.getAPIServices()

        # Get rid of previously made slides
        self.removePreviousSlides()

        # Generate new slide and save its ID
        self.newSlideID = self.getDuplicatePresentation(type)

        # Slide change requests are appended here
        self.requests: List[dict] = []

        # Get access to slide data
        self.presentation = self.slideService.presentations().get(
            presentationId=self.newSlideID).execute()

        # Update local hymn database
        self.updateHymnDataBase()

    # ==========================================================================================
    # ======================================= API TOOLS ========================================
    # ==========================================================================================

    def getAPIServices(self) -> List[googleapiclient.discovery.Resource]:
        # Refer to https://developers.google.com/slides/api/quickstart/python
        creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists('Data/token.pickle'):
            creds = Credentials.from_authorized_user_file('Data/token.pickle', self.scope)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'Data/credentials.json', self.scope)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('Data/token.pickle', 'w') as token:
                token.write(creds.to_json())

        slideService = build('slides', 'v1', credentials=creds)
        sheetService = build('sheets', 'v4', credentials=creds)
        driveService = build('drive', 'v3', credentials=creds)

        return [slideService, sheetService, driveService]

    def commitSlideChanges(self) -> bool:
        # Commit changes to slides, reset requests, and update data
        successfulCommit = True
        if len(self.requests) > 0:
            try:
                self.slideService.presentations().batchUpdate(
                    presentationId=self.newSlideID, body={'requests': self.requests}).execute()
            except errors.HttpError as error:
                print(f"\tERROR : An error occurred on committing slide changes; {error}")
                successfulCommit = False

        self.requests = []
        self.presentation = self.slideService.presentations().get(
            presentationId=self.newSlideID).execute()

        return successfulCommit

    # ==========================================================================================
    # =================================== SLIDE DATA GETTERS ===================================
    # ==========================================================================================

    def getTotalSlideNumber(self) -> int:
        # Returns the total number of slides
        return len(self.presentation.get('slides'))

    def getText(self, pageElement: dict) -> str:
        # Returns the first block of formatted text from an element
        try:
            return pageElement['shape']['text']['textElements'][1]['textRun']['content']
        except:
            return ""

    def getSlideTextData(self, index: int) -> List[List[str]]:
        # Returns the objectID and text from the textboxes in the indexed slide
        textObjects = []
        for element in self.presentation.get('slides')[index]['pageElements']:
            textObject = [element.get('objectId'), self.getText(element)]
            if textObject[1] != "":
                textObjects.append(textObject)
        return textObjects

    def getSlideID(self, index: int) -> str:
        return self.presentation.get('slides')[index]['objectId']

    # ==========================================================================================
    # =================================== SLIDE MODIFIERS ======================================
    # ==========================================================================================

    def duplicateSlide(self, slideObjectID: str, newSlideObjectID: str) -> None:
        # Duplicates a slide, the duplicated slide is placed right after the source. "newSlideObjectID" must be unique.
        self.requests.append({"duplicateObject": {"objectId": slideObjectID,
                                                  "objectIds": {slideObjectID: newSlideObjectID}}})

    def deleteSlide(self, slideObjectID: str) -> None:
        # Delete the slide with the "slideObjectID"
        self.requests.append({"deleteObject": {"objectId": slideObjectID}})

    # ==========================================================================================
    # ================================= SLIDE FORMAT SETTERS ===================================
    # ==========================================================================================

    def setText(self, objectID: str, newText: str) -> None:
        # Delete existing text and insert new
        self.requests.append({"deleteText": {"objectId": objectID}})
        self.requests.append({"insertText": {"objectId": objectID, "text": newText}})

    def setBold(self, objectID: str, startIndex: int, endIndex: int) -> None:
        # Set bold to a select range of text
        self.requests.append({"updateTextStyle": {"objectId": objectID,
                                                  "textRange": {"type": "FIXED_RANGE", "startIndex": startIndex, "endIndex": endIndex},
                                                  "style": {"bold": True},
                                                  "fields": "bold"}})

    def setTextStyle(self, objectID: str, bold: bool, italic: bool, underline: bool, size: int) -> None:
        # Sets bold, italic, or underline to "True" or "False" to enable or disable; also the entire object's font size.
        self.requests.append({"updateTextStyle": {"objectId": objectID,
                                                  "style": {"bold": bold, "italic": italic, "underline": underline, "fontSize": {"magnitude": size, "unit": "PT"}},
                                                  "fields": "bold, italic, underline, fontSize"}})

    def setParagraphStyle(self, objectID: str, spacing: int, alignment: str) -> None:
        # Sets the space between each line, default is 100.0; alignment options includes "START" (aka 'left'), "CENTER", "END" (aka 'right'), and "JUSTIFIED"
        self.requests.append({"updateParagraphStyle": {"objectId": objectID,
                                                       "style": {"lineSpacing": spacing, "alignment": alignment},
                                                       "fields": "lineSpacing, alignment"}})

    def setTextSuperScript(self, objectID: str, startIndex: int, endIndex: int) -> None:
        # Formats text indexed from 'startIndex' to 'endIndex' to superscript
        self.requests.append({"updateTextStyle": {"objectId": objectID,
                                                  "textRange": {"type": "FIXED_RANGE", "startIndex": startIndex, "endIndex": endIndex},
                                                  "style":  {"baselineOffset": "SUPERSCRIPT"},
                                                  "fields": "baselineOffset"}})

    def setSpaceAbove(self, objectID: str, paragraphIndex: int, units: int) -> None:
        # Adds spacing above a paragraph, any index within the desired line will work
        self.requests.append({"updateParagraphStyle": {"objectId": objectID,
                                                       "textRange": {"type": "FIXED_RANGE", "startIndex": paragraphIndex, "endIndex": paragraphIndex + 1},
                                                       "style": {"spaceAbove": {"magnitude": units, "unit": "PT"}},
                                                       "fields": "spaceAbove"}})

    def setParagraphBullet(self, objectID: str, startIndex: int, endIndex: int) -> None:
        # Add digit paragraph bullets to each paragraph
        self.requests.append({"createParagraphBullets": {"objectId": objectID,
                                                         "textRange": {"type": "FIXED_RANGE", "startIndex": startIndex, "endIndex": endIndex}}})

    # ==========================================================================================
    # ================================= SLIDE FORMAT UPDATERS ==================================
    # ==========================================================================================

    def updatePageElementTransform(self, objectID: str, scaleX: int = 1, scaleY: int = 1, translateX: int = 0, translateY: int = 0) -> None:
        # Horizontally and vertically scale or translate slide objects
        self.requests.append({"updatePageElementTransform": {"objectId": objectID,
                                                             "applyMode": "RELATIVE",
                                                             "transform": {"scaleX": scaleX, "scaleY": scaleY,
                                                                           "translateX": translateX, "translateY": translateY, "unit": "EMU"}}})

    # ==========================================================================================
    # =================================== SPREADSHEET GETTERS ==================================
    # ==========================================================================================

    def getAnnouncements(self) -> List[str]:
        # Get announcement entries from Google Sheet
        sheetID = self.globalConfig["SLIDE_MAKER_SHEET"]["SlideMakerSheetFileID"]
        dataRange = self.globalConfig["SLIDE_MAKER_SHEET"]["SlideMakerSheetAnnouncementsRange"]

        try:
            response = self.sheetService.spreadsheets().values().get(spreadsheetId=sheetID, range=dataRange).execute()

            # Flatten the nested list
            return [val for sublist in response["values"] for val in sublist]
        except errors.HttpError as error:
            print(f"\tERROR : An error occurred on retrieving announcement data; {error}")

        return []

    def getSupplications(self) -> List[str]:
        # Get supplication entries from Google Sheet
        sheetID = self.globalConfig["SLIDE_MAKER_SHEET"]["SlideMakerSheetFileID"]
        dataRange = self.globalConfig["SLIDE_MAKER_SHEET"]["SlideMakerSheetSupplicationsRange"]

        try:
            response = self.sheetService.spreadsheets().values().get(spreadsheetId=sheetID, range=dataRange).execute()

            # Flatten the nested list
            return [val for sublist in response["values"] for val in sublist]
        except errors.HttpError as error:
            print(f"\tERROR : An error occurred on retrieving supplication data; {error}")

        return []

    # ==========================================================================================
    # ====================================== MISC GETTERS ======================================
    # ==========================================================================================

    def getNextSundayDate(self) -> datetime.date:
        # Get datetime variable with the date of next Sunday
        dt = datetime.date.today()
        dt += timedelta(days=(6 - dt.weekday()))
        return dt

    def getFormattedNextSundayDate(self, type: DateFormatMode) -> Tuple[str, int]:
        # Get formatted string with the date of next Sunday
        dt = self.getNextSundayDate()

        month = dt.strftime('%B') if type == self.DateFormatMode.Full else dt.strftime('%b')
        day = dt.strftime('%d')
        year = dt.strftime('%Y')

        # Get rid of leading zero in day
        if (day[0] == "0"):
            day = day[1]

        lastNum = day[len(day) - 1]
        if len(day) > 1 and day[0] != '1':
            ordinal = 'st' if lastNum == '1' else 'nd' if lastNum == '2' else 'rd' if lastNum == '3' else 'th'
        else:
            ordinal = 'th'
        return (f'{month} {day}{ordinal} {year}', len(month) + len(day) + 1)  # Return string and index of the ordinal for superscripting

    def getUpcomingSlideTitle(self, type: str) -> str:
        # Get slide file name for upcoming Sunday
        dt = self.getFormattedNextSundayDate(self.DateFormatMode.Short)[0]
        return f'Sunday Worship Slides {dt} - {type}'

    def openSlideInBrowser(self) -> None:
        # Access may be denied due to slide permissions (HINT: Set source slide URL with editor permission)
        webbrowser.open(f'https://docs.google.com/presentation/d/{self.newSlideID}')

    # ==========================================================================================
    # =================================== DRIVE CHANGE TOOLS ===================================
    # ==========================================================================================

    def removePreviousSlides(self) -> None:
        # Delete all previously created slide files on drive
        if os.path.exists("Data/SlideIDList.txt"):
            with open("Data/SlideIDList.txt", "r+") as f:
                lines = f.readlines()

                for line in lines:
                    try:
                        # Get rid of the new line symbol in the ID
                        self.driveService.files().delete(fileId=line[:-1]).execute()
                    except errors.HttpError as error:
                        print(f"ERROR : An error occurred on slide removal; {error}")

                # Clear out the file
                f.truncate(0)

    def getDuplicatePresentation(self, type: str) -> str:
        # Generates a duplicate presentation from source slide
        body = {
            'name': self.getUpcomingSlideTitle(type)
        }

        drive_response = {}
        try:
            drive_response = self.driveService.files().copy(
                fileId=self.sourceSlideID, body=body).execute()
        except errors.HttpError as error:
            print(f"ERROR : An error occurred on slide duplication; {error}")

        # Write ID to file, so it can be deleted later
        newID = str(drive_response.get('id'))
        with open("Data/SlideIDList.txt", "a") as f:
            f.write(newID + "\n")

        return newID

    # ==========================================================================================
    # =================================== LOCAL CHANGE TOOLS ===================================
    # ==========================================================================================

    def updateHymnDataBase(self) -> None:
        # Lookup latest HymnDatabase file on Google Drive, replace local copy if local copy is older
        try:
            fileID = self.globalConfig["HYMN_DATABASE_PROPERTIES"]["HymnDataBaseFileID"]
            filedDetails = self.driveService.files().get(fileId=fileID,
                                                         fields="modifiedTime").execute()

            # Get modified date of DataBase.db file and compare
            localModifiedDate = pytz.utc.localize(datetime.datetime.min)
            driveModifiedDate = pytz.utc.localize(datetime.datetime.strptime(filedDetails['modifiedTime'], '%Y-%m-%dT%H:%M:%S.%fZ'))

            if os.path.exists("Data/HymnDatabase.db"):
                localModifiedDate = datetime.datetime.fromtimestamp(os.path.getmtime("Data/HymnDatabase.db"), datetime.timezone.utc)

            # Overwrite local file
            if localModifiedDate < driveModifiedDate:
                Logging.writeLog(Logging.LogType.Info, f"GoogleAPITools - Updating local hymn database from [{localModifiedDate}] to [{driveModifiedDate}]")
                request = self.driveService.files().get_media(fileId=fileID)
                with open("Data/HymnDatabase.db", "wb") as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while done is False:
                        status, done = downloader.next_chunk()
                        print("UPDATING HYMN DATABASE : %d%%" % int(status.progress() * 100))
        except errors.HttpError as error:
            print(f"ERROR : An error occurred on updating local hymn database; {error}")


if __name__ == '__main__':
    peS = GoogleAPITools('Stream')

    anns = peS.getAnnouncements()
    sups = peS.getSupplications()

    for ann in anns:
        print(ann)
        print("---------------------")

    for sup in sups:
        print(sup)
        print("---------------------")
