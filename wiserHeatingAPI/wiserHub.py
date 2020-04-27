"""
# Wiser API Facade

Angelosantagata@gmail.com


https://github.com/asantaga/wiserheatingapi


This API Facade allows you to communicate with your wiserhub.
This API is used by the homeassistant integration available at
https://github.com/asantaga/wiserHomeAssistantPlatform
"""

import logging
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry # pylint: disable=import-error
from request_mod import CustomSession
import json
import os
import re

_LOGGER = logging.getLogger(__name__)

"""
Wiser Data URLS
"""
WISERSETROOMTEMP = "domain/Room/{}"
WISERROOM = "domain/Room/{}"
WISERSCHEDULEURL = "schedules/Heating/{}"
WISERSMARTPLUGURL = "domain/SmartPlug/{}"
WISERSMARTPLUGSURL = "http://{}/data/v2/domain/SmartPlug"

WISERBASEURL = "http://{}/data/v2/"

TEMP_MINIMUM = 5    
TEMP_MAXIMUM = 30
TEMP_OFF = -20

TIMEOUT = (1.5, 1.0)
RETRIES = 3

__VERSION__ = "1.0.8.0"

"""
Exception Handlers
"""

class Error(Exception):
    """Base class for exceptions in this module."""

    pass


class WiserNoDevicesFound(Error):
    pass


class WiserNotFound(Error):
    pass


class WiserNoHotWaterFound(Error):
    pass


class WiserNoHeatingFound(Error):
    pass


class WiserRESTException(Error):
    pass


class WiserHubDataNull(Error):
    _LOGGER.info("WiserHub data null after refresh")
    pass


class WiserHubAuthenticationException(Error):
    pass


class WiserHubRequestException(Error):
    pass


class WiserHubTimeoutException(Error):
    pass


class WiserNoRoomsFound(Error):
    pass


class wiserHub:
    def __init__(self, hubIP, secret):
        _LOGGER.info("WiserHub API Initialised : Version {}".format(__VERSION__))
        self._http = CustomSession(
            base_url=WISERBASEURL.format(hubIP),
            hub_secret=secret,
            timeout=TIMEOUT,
            num_retries=RETRIES
        )
        self.wiserHubData = None
        self.wiserNetworkData = None
        self.wiserScheduleData = None
        # Dict holding Valve2Room mapping convinience variable
        self.device2roomMap = {}

    def _toWiserTemp(self, temp):
        """
        Converts from temperature to wiser hub format
        param temp: The temperature to convert
        return: Integer
        """
        temp = int(temp * 10)
        return temp

    def _fromWiserTemp(self, temp):
        """
        Converts from wiser hub temperature format to decimal value
        param temp: The wiser temperature to convert
        return: Float
        """
        temp = round(temp / 10, 1)
        return temp

    def _checkTempRange(self, temp):
        """
        Validates temperatures are within the allowed range for the wiser hub
        param temp: The temperature to check
        return: Boolean
        """
        if temp != TEMP_OFF and (temp < TEMP_MINIMUM or temp > TEMP_MAXIMUM):
            return False
        else:
            return True

    def _makeGetRequest(self, url):
        try:
            resp = self._http.get(url=url)
            return resp
        except requests.HTTPError as ex:
            if resp.status_code == 401:
                raise WiserHubAuthenticationException("Authentication error. Check secret key.")
            elif resp.status_code == 404:
                raise WiserHubRequestException("Invalid request. Check URL endpoint.")
            else:
                raise WiserRESTException(ex)
        except (requests.Timeout, requests.ConnectionError) as ex:
            _LOGGER.debug("Connection timed out trying to update from Wiser Hub")
            raise WiserHubTimeoutException("The error is {} The Exception is {}".format(ex, type(ex)))

    def _makePatchRequest(self, url, data):
        try:
            resp = self._http.patch(url=url, json=data)
            return resp
        except requests.HTTPError as ex:
            if resp.status_code == 401:
                raise WiserHubAuthenticationException("Authentication error. Check secret key.")
            elif resp.status_code == 404 or 405:
                raise WiserHubRequestException("Invalid request. Check URL endpoint and patch data.")
            else:
                raise WiserRESTException(ex)
        except (requests.Timeout, requests.ConnectionError) as ex:
            _LOGGER.debug("Connection timed out trying to send data to Wiser Hub")
            raise WiserHubTimeoutException("The error is {} The Exception is {}".format(ex, type(ex)))

    def checkHubData(self):
        """
        Method checks the hub data object is populated, if it is not then it
        executes the refresh method, if the hubdata object is still null then
        it raises an error
        """
        if self.wiserHubData is None:
            self.refreshData()
        if self.wiserHubData is None:
            raise WiserHubDataNull("Hub data null even after refresh, aborting request")
        # Otherwise continue
        
    def updateScheduleData(self):
        """
        Gets the latest schedule data from the Wiser Hub
        return: JSON Data
        """
        self.wiserScheduleData = self._makeGetRequest(url='schedules/').json()
        return self.wiserScheduleData

    def updateNetworkData(self):
        """
        Gets the latest network data from the Wiser Hub
        return: JSON Data
        """
        responseContent = self._makeGetRequest(url='network/').content
        responseContent = re.sub(rb"[^\x20-\x7F]+", b"", responseContent)
        self.wiserNetworkData = json.loads(responseContent)
        return self.wiserNetworkData

    def updateHubData(self):
        """
        Gets the latest data from the Wiser Hub
        return: JSON Data
        """
        self.wiserHubData = self._makeGetRequest(url='domain/').json()
        return self.wiserHubData

    def refreshData(self):
        """
        Forces a refresh of data from the Wiser Hub
        return: JSON Data
        """
        _LOGGER.info("Updating Wiser Hub Data")

        if self.wiserScheduleData is None:
            self.updateScheduleData()

        if self.wiserNetworkData is None:
            self.updateNetworkData()

        self.updateHubData()

        _LOGGER.debug("Wiser Hub Data received {} ".format(self.wiserHubData))
        if self.getRooms() is not None:
            for room in self.getRooms():
                roomStatId = room.get("RoomStatId")
                if roomStatId is not None:
                    # RoomStat found add it to the list
                    self.device2roomMap[roomStatId] = {
                        "roomId": room.get("id"),
                        "roomName": room.get("Name"),
                    }
                smartValves = room.get("SmartValveIds")
                if smartValves is not None:
                    for valveId in smartValves:
                        self.device2roomMap[valveId] = {
                            "roomId": room.get("id"),
                            "roomName": room.get("Name"),
                        }
                # Show warning if room contains no devices.
                if roomStatId is None and smartValves is None:
                    # No devices in room
                    _LOGGER.warning(
                        "Room {} doesn't contain any smart valves or thermostats.".format(
                            room.get("Name")
                        )
                    )
            _LOGGER.debug(" valve2roomMap{} ".format(self.device2roomMap))
        else:
            _LOGGER.warning("Wiser found no rooms")
        
        # Add v2 Schedule data to v2 Hub data so existing HA component will still work
        tempData = self.wiserHubData
        tempData['Schedule'] = self.wiserScheduleData['Heating']

        return tempData

    def getHubData(self):
        """
        Retrieves the full JSON payload,
        for functions where I haven't provided an API yet
        
        returns : JSON Data
        """
        self.checkHubData()
        return self.wiserHubData

    def getWiserHubName(self):
        try:
            return self.wiserNetworkData.get("Station").get("MdnsHostname")
        except:
            return self.getDevice(0).get("ModelIdentifier")

    def getMACAddress(self):
        try:
            return self.wiserNetworkData.get("Station").get("MacAddress")
        except:
            return "NO_MAC_FOUND"

    def getRooms(self):
        """
        Gets Room Data as JSON Payload
        """
        self.checkHubData()
        return self.wiserHubData.get("Room")

    def getRoom(self, roomId):
        """
        Convinience to get data on a single room

        param roomId: The roomID
        return:
        """
        self.checkHubData()
        if self.wiserHubData.get("Room") is None:
            _LOGGER.warning("getRoom called but no rooms found")
            raise WiserNoRoomsFound("No rooms found in Wiser payload")
        for room in self.wiserHubData.get("Room"):
            if room.get("id") == roomId:
                return room
        raise WiserNotFound("Room {} not found".format(roomId))

    def getSystem(self):
        """
        Convinience function to get system information

        return: JSON with system data
        """
        self.checkHubData()
        return self.wiserHubData.get("System")

    def getHotwater(self):
        """
        Convinience function to get hotwater data

        return: JSON with hotwater data
        """
        self.checkHubData()
        try:
            return self.wiserHubData.get("HotWater")
        except:
            return None

    def getHeatingChannels(self):
        """
        Convinience function to get heating channel data

        return: JSON data
        """
        self.checkHubData()
        return self.wiserHubData.get("HeatingChannel")

    def getDevices(self):
        """
        Convinience function to get devices data

        return: JSON data
        """
        self.checkHubData()

        return self.wiserHubData.get("Device")

    def getDevice(self, deviceId):
        """
        Get single devices data

        param deviceId:
        return: Device JSON Data
        """
        self.checkHubData()

        if self.wiserHubData.get("Device") is None:
            _LOGGER.warning("getRoom called but no rooms found")
            raise WiserNoRoomsFound("getRoom called but no rooms found")
        for device in self.wiserHubData.get("Device"):
            if device.get("id") == deviceId:
                return device
        raise WiserNotFound("Device {} not found ".format(deviceId))

    def getDeviceRoom(self, deviceId):
        """
        Convinience function to return the name of a room which is associated
        with a device (roomstat or trf)
        param deviceId:
        return: Name of Room associated with a device ID
        """
        self.checkHubData()
        _LOGGER.debug(
            " getDeviceRoom called, valve2roomMap is {} ".format(self.device2roomMap)
        )
        if not self.device2roomMap:
            self.refreshData()
        # This will return None if no device found, thats ok
        return self.device2roomMap[deviceId]

    def getHeatingRelayStatus(self):
        """
        Returns heating relay status
        return:  On or Off
        """
        # self.checkHubData() ????????????????
        heatingRelayStatus = "Off"
        # There could be multiple heating channels,
        heatingChannels = self.getHeatingChannels()
        for heatingChannel in heatingChannels:
            if heatingChannel.get("HeatingRelayState") == "On":
                heatingRelayStatus = "On"
        return heatingRelayStatus

    def getHotwaterRelayStatus(self):
        """
        Returns hotwater relay status
        
        return:  On or Off
        """
        self.checkHubData()
        # If there is no hotwater object then return false
        if not self.wiserHubData.get("HotWater"):
            return False

        return self.wiserHubData.get("HotWater")[0].get("WaterHeatingState")

    def setHotwaterMode(self, mode):
        """
          Switch Hot Water on or off manually, or reset to 'Auto' (schedule).
          'mode' can be "on", "off" or "auto".
        """

        # Wiser requires a temperature when patching the Hot Water state,
        # reflecting 'on' or 'off'
        DHWOnTemp = 1100
        DHWOffTemp = -200

        modeMapping = {
            "on": {"RequestOverride": {"Type": "Manual", "SetPoint": DHWOnTemp}},
            "off": {"RequestOverride": {"Type": "Manual", "SetPoint": DHWOffTemp}},
            "auto": {"RequestOverride": {"Type": "None", "Mode": "Auto"}},
        }

        _mode = mode.lower()
        if _mode not in ["on", "off", "auto"]:
            raise ValueError(
                "Hot Water can be either 'on', 'off' or 'auto' - not '%s'" % _mode
            )

        # Obtain our DHW control ID
        if self.wiserHubData is None:
            self.refreshData()
        DHWId = self.wiserHubData.get("HotWater")[0].get("id")
        _url = "HotWater/{}/".format(DHWId)
        _LOGGER.debug(
            "Sending Patch Data: {}, to URL [{}]".format(modeMapping.get(_mode), _url)
        )
        response = self._http.patch(
            url=_url,
            json=modeMapping.get(_mode)
        )
        if response.status_code != 200:
            _LOGGER.debug("Set DHW Response code = {}".format(response.status_code))
            raise WiserRESTException(
                "Error setting hot water mode to {}, error {} {}".format(
                    _mode, response.status_code, response.text
                )
            )

        return True

    def setSystemSwitch(self, switch, mode=False):
        """
        Sets a system switch. For details of which switches to set look at the System section of the payload from the wiserhub
        :param switch: Name of Switch
        :param mode: Value of mode
        :return:
        """
        patchData = {switch: mode}

        _LOGGER.debug("patchdata {} ".format(patchData))
        response = self._http.patch(
            url="System",
            json=patchData
        )
        if response.status_code != 200:
            _LOGGER.debug(
                "Set {} Response code = {}".format(switch, response.status_code)
            )
            raise WiserRESTException(
                "Error setting {} , error {} {}".format(
                    switch, response.status_code, response.text
                )
            )

    def getRoomStatData(self, deviceId):
        """
        Gets Room Thermostats Data

        param deviceId:
        return:
        """
        self.checkHubData()

        if self.wiserHubData["RoomStat"] is None:
            _LOGGER.warning("getRoomStatData called but no RoomStats found")
            raise WiserNotFound("deviceID {} not found ".format(deviceId))

        for roomStat in self.wiserHubData["RoomStat"]:
            if roomStat.get("id") == deviceId:
                return roomStat
        """
        If we get here then the deviceId was not found
        """
        raise WiserNotFound(
            "getRoomStatData for deviceID {} not found due".format(deviceId)
        )

    def getRoomSchedule(self, roomId):
        """
        Gets Room Schedule Data
        
        param roomId:
        return: json data
        """
        self.checkHubData()

        if self.getRoom(roomId) is None:
            raise WiserNotFound("getRoomSchedule for room {} not found ".format(roomId))

        scheduleId = self.getRoom(roomId).get("ScheduleId")
        if scheduleId is not None:
            for schedule in self.wiserHubData.get("Schedule"):
                if schedule.get("id") == scheduleId:
                    return schedule
            raise WiserNotFound("getRoomSchedule for room {} not found ".format(roomId))
        else:
            raise WiserNotFound("getRoomSchedule for room {} not found ".format(roomId))

    def setRoomSchedule(self, roomId, scheduleData: dict):
        """
        Sets Room Schedule

        param roomId:
        param scheduleData: json data for schedule
        return:
        """
        scheduleId = self.getRoom(roomId).get("ScheduleId")

        if scheduleId is not None:
            patchData = scheduleData
            response = self._http.patch(
                url="schedules/Heating/{}".format(scheduleId),
                json=patchData
            )

            if response.status_code != 200:
                _LOGGER.debug(
                    "Set Schedule Response code = {}".format(response.status_code)
                )
                raise WiserRESTException(
                    "Error setting schedule for room {} , error {} {}".format(
                        roomId, response.status_code, response.text
                    )
                )
        else:
            raise WiserNotFound("No schedule found that matches roomId")

    def setRoomScheduleFromFile(self, roomId, scheduleFile: str):
        """
        Sets Room Schedule

        param roomId:
        param scheduleData: json data for schedule
        return:
        """
        scheduleId = self.getRoom(roomId).get("ScheduleId")

        if scheduleId is not None:
            if os.path.exists(scheduleFile):
                try:
                    with open(scheduleFile, "r") as f:
                        scheduleData = json.load(f)
                except:
                    raise Exception("Error reading file {}".format(scheduleFile))

                patchData = scheduleData
                response = self._http.patch(
                    url="schedules/Heating/{}".format(scheduleId),
                    json=patchData
                )

                if response.status_code != 200:
                    _LOGGER.debug(
                        "Set Schedule Response code = {}".format(response.status_code)
                    )
                    raise WiserRESTException(
                        "Error setting schedule for room {} , error {} {}".format(
                            roomId, response.status_code, response.text
                        )
                    )
            else:
                raise FileNotFoundError(
                    "Schedule file, {}, not found.".format(
                        os.path.abspath(scheduleFile)
                    )
                )
        else:
            raise WiserNotFound("No schedule found that matches roomId")

    def copyRoomSchedule(self, fromRoomId, toRoomId):
        """
        Copies Room Schedule from one room to another

        param fromRoomId:
        param toRoomId:
        return: boolean
        """
        scheduleData = self.getRoomSchedule(fromRoomId)

        print(json.dumps(scheduleData))

        print("TYPE:{}".format(type(scheduleData)))

        if scheduleData is not None:
            self.setRoomSchedule(toRoomId, scheduleData)
        else:
            raise WiserNotFound(
                "Error copying schedule.  One of the room Ids is not valid"
            )

    def setHomeAwayMode(self, mode, temperature=10):
        """
        Sets default Home or Away mode, optionally allows you to set a temperature for away mode

        param mode: HOME   | AWAY

        param temperature: Temperature between 5-30C or -20 for OFF

        return:
        """
        _LOGGER.info("Setting Home/Away mode to : {} {} C".format(mode, temperature))

        if mode not in ["HOME", "AWAY"]:
            raise ValueError("setAwayHome can only be HOME or AWAY")

        if mode == "AWAY":
            if temperature is None:
                raise ValueError("setAwayHome set to AWAY but not temperature set")
            if not (self._checkTempRange(temperature)):
                raise ValueError(
                    "setAwayHome temperature can only be between {} and {} or {}(Off)".format(
                        TEMP_MINIMUM, TEMP_MAXIMUM, TEMP_OFF
                    )
                )
        _LOGGER.info("Setting Home/Away : {}".format(mode))

        if mode == "AWAY":
            patchData = {"type": 2, "setPoint": self._toWiserTemp(temperature)}
        else:
            patchData = {"type": 0, "setPoint": 0}
        _LOGGER.debug("patchdata {} ".format(patchData))
        response = self._http.patch(
            url="System/RequestOverride",
            json=patchData
        )
        if response.status_code != 200:
            _LOGGER.debug(
                "Set Home/Away Response code = {}".format(response.status_code)
            )
            raise ValueError(
                "Error setting Home/Away , error {} {}".format(
                    response.status_code, response.text
                )
            )

    def setRoomTemperature(self, roomId, temperature):
        """
        Sets the room temperature
        param roomId:  The Room ID
        param temperature:  The temperature in celcius from 5 to 30, -20 for Off
        """
        _LOGGER.info("Set Room {} Temperature to = {} ".format(roomId, temperature))
        if not (self._checkTempRange(temperature)):
            raise ValueError(
                "SetRoomTemperature : value of temperature must be between {} and {} OR {} (off)".format(
                    TEMP_MINIMUM, TEMP_MAXIMUM, TEMP_OFF
                )
            )
        patchData = {
            "RequestOverride": {
                "Type": "Manual",
                "SetPoint": self._toWiserTemp(temperature),
            }
        }
        response = self._http.patch(
            url="domain/Room/{}".format(roomId),
            json=patchData
        )
        if response.status_code != 200:
            _LOGGER.error(
                "Set Room {} Temperature to = {} resulted in {}".format(
                    roomId, temperature, response.status_code
                )
            )
            raise WiserRESTException(
                "Error setting temperature, error {} ".format(response.text)
            )
        _LOGGER.debug(
            "Set room Temp, error {} ({})".format(response.status_code, response.text)
        )

    # Set Room Mode (Manual, Boost,Off or Auto )
    # If set to off then the trv goes to manual and temperature of -200
    #
    def setRoomMode(self, roomId, mode, boost_temp=20, boost_temp_time=30):
        """
        Set the Room Mode, this can be Auto, Manual, off or Boost. When you set the mode back to Auto it will automatically take the scheduled temperature

        param roomId: RoomId

        param mode:  Mode (auto, manual off, or boost)

        param boost_temp:  If boosting enter the temperature here in C, can be between 5-30

        param boost_temp_time:  How long to boost for in minutes

        """
        # TODO
        _LOGGER.debug("Set Mode {} for a room {} ".format(mode, roomId))
        if mode.lower() == "auto":
            # Do Auto
            patchData = {"Mode": "Auto"}
        elif mode.lower() == "boost":
            if boost_temp < TEMP_MINIMUM or boost_temp > TEMP_MAXIMUM:
                raise ValueError(
                    "Boost temperature is set to {}. Boost temperature can only be between {} and {}.".format(
                        boost_temp, TEMP_MINIMUM, TEMP_MAXIMUM
                    )
                )
            _LOGGER.debug(
                "Setting room {} to boost mode with temp of {} for {} mins".format(
                    roomId, boost_temp, boost_temp_time
                )
            )
            patchData = {
                "RequestOverride": {
                    "Type": "Manual",
                    "DurationMinutes": boost_temp_time,
                    "SetPoint": self._toWiserTemp(boost_temp),
                    "Originator": "App",
                }
            }
        elif mode.lower() == "manual":
            # When setting to manual , set the temp to the current scheduled temp
            setTemp = self._fromWiserTemp(
                self.getRoom(roomId).get("ScheduledSetPoint")
            )
            # If current scheduled temp is less than 5C then set to min temp
            setTemp = setTemp if setTemp >= TEMP_MINIMUM else TEMP_MINIMUM
            patchData = {
                "Mode": "Manual",
                "RequestOverride": {
                    "Type": "Manual",
                    "SetPoint": self._toWiserTemp(setTemp),
                },
            }
        # Implement trv off as per https://github.com/asantaga/wiserheatingapi/issues/3
        elif mode.lower() == "off":
            patchData = {
                "Mode": "Manual",
                "RequestOverride": {
                    "Type": "Manual",
                    "SetPoint": self._toWiserTemp(TEMP_OFF),
                },
            }
        else:
            raise ValueError(
                "Error setting setting room mode, received  {} but should be auto,boost,off or manual ".format(
                    mode
                )
            )

        # if not a boost operation cancel any current boost
        if mode.lower() != "boost":
            cancelBoostPostData = {
                "RequestOverride": {
                    "Type": "None",
                    "DurationMinutes": 0,
                    "SetPoint": 0,
                    "Originator": "App",
                }
            }

            response = self._http.patch(
                "domain/Room/{}".format(roomId),
                json=cancelBoostPostData
            )
            if response.status_code != 200:
                _LOGGER.error(
                    "Cancelling boost resulted in {}".format(response.status_code)
                )
                raise WiserRESTException("Error cancelling boost {} ".format(mode))

        # Set new mode
        response = self._http.patch(
            "domain/Room/{}".format(roomId),
            json=patchData
        )
        if response.status_code != 200:
            _LOGGER.error(
                "Set Room {} to Mode {} resulted in {}".format(
                    roomId, mode, response.status_code
                )
            )
            raise WiserRESTException(
                "Error setting mode to {}, error {} ".format(mode, response.text)
            )
        _LOGGER.debug(
            "Set room mode, error {} ({})".format(response.status_code, response.text)
        )

    def getSmartPlugs(self):
        self.checkHubData()
        return self.getHubData().get("SmartPlug")

    def getSmartPlug(self, smartPlugId):
        self.checkHubData()
        if self.getHubData().get("SmartPlug") is not None:
            for plug in self.getHubData().get("SmartPlug"):
                if plug.get("id") == smartPlugId:
                    return plug
        # If we get here then the plug was not found
        raise WiserNotFound("Unable to find smartPlug {}".format(smartPlugId))

    def getSmartPlugState(self, smartPlugId):
        self.checkHubData()
        if self.getHubData().get("SmartPlug") is not None:
            for plug in self.getHubData().get("SmartPlug"):

                if plug.get("id") == smartPlugId:
                    if plug.get("OutputState") is None:
                        raise WiserNotFound(
                            "Unable to get State of smartPlug {}, is it offline?".format(
                                smartPlugId
                            )
                        )
                    else:
                        return plug.get("ScheduledState")
        # If we get here then the plug was not found
        raise WiserNotFound("Unable to find smartPlug {}".format(smartPlugId))

    def setSmartPlugState(self, smartPlugId, smartPlugState):
        if smartPlugState is None:
            _LOGGER.error("SmartPlug State is None, must be either On or Off")
            raise ValueError("SmartPlug State is None, must be either On or Off")
        if smartPlugState.title() not in ["On", "Off"]:
            _LOGGER.error("SmartPlug State must be either On or Off")
            raise ValueError("SmartPlug State must be either On or Off")

        patchData = {"RequestOutput": smartPlugState.title()}

        _LOGGER.debug("Setting smartplug status patchdata {} ".format(patchData))
        response = self._http.patch(
            url="domain/SmartPlug/{}".format(smartPlugId),
            json=patchData
        )
        if response.status_code != 200:
            if response.status_code == 404:
                _LOGGER.debug("Set smart plug not found error ")
                raise WiserNotFound(
                    "Set smart plug {} not found error".format(smartPlugId)
                )
            else:
                _LOGGER.debug(
                    "Set smart plug error {} Response code = {}".format(
                        response.text, response.status_code
                    )
                )
                raise WiserRESTException(
                    "Error setting smartplug mode, msg {} , error {}".format(
                        response.status_code, response.text
                    )
                )

    def getSmartPlugMode(self, smartPlugId):
        self.checkHubData()
        if self.getHubData().get("SmartPlug") is not None:
            for plug in self.getHubData().get("SmartPlug"):
                if plug.get("id") == smartPlugId:
                    return plug.get("Mode")
        # If we get here then the plug was not found
        raise WiserNotFound("Unable to find smartPlug {}".format(smartPlugId))

    def setSmartPlugMode(self, smartPlugId, smartPlugMode):

        if smartPlugMode.title() not in ["Auto", "Manual"]:
            _LOGGER.error("SmartPlug Mode must be either Auto or Manual")
            raise ValueError("SmartPlug Mode must be either Auto or Manual")

        patchData = {"Mode": smartPlugMode.title()}

        _LOGGER.debug("Setting smartplug status patchdata {} ".format(patchData))
        response = self._http.patch(
            url="domain/SmartPlug/{}".format(smartPlugId),
            json=patchData
        )
        if response.status_code != 200:
            if response.status_code == 404:
                _LOGGER.debug("Set smart plug not found error ")
                raise WiserNotFound(
                    "Set smart plug {} not found error".format(smartPlugId)
                )
            else:
                _LOGGER.debug(
                    "Set smart plug error {} Response code = {}".format(
                        response.text, response.status_code
                    )
                )
                raise WiserRESTException(
                    "Error setting smartplug mode, msg {} , error {}".format(
                        response.status_code, response.text
                    )
                )
