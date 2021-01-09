#!/usr/bin/python

import requests
import logging
import xmltodict
import threading
import logging
from bs4 import BeautifulSoup
import datetime
import time
import xml.etree.cElementTree as ET

logger = logging.getLogger(__file__)
logger.setLevel(logging.DEBUG)


class Client:

    HOME_URL = 'http://192.168.0.1/html/home.html'  #check to make sure your HuaweiE3372 LAN IP Address is actually correct
    API_URL = 'http://192.168.0.1/api/'             #check to make sure your HuaweiE3372 LAN IP address is actually correct

    def __init__(self, host='192.168.0.1'):
        self.home_url = self.HOME_URL.format(host=host)
        self.api_url = self.API_URL.format(host=host)
        self.session = requests.Session()
        self.connected = False
        self.sms_module_connected = False
        self.api_headers = {}
        self.sms_module_headers = {}
        self.SMSAllboxMsgCountLastRefreshTime = 0
        self.SMSInboxContent = None
        self.SMSSentboxContent = None
        self.DEBUG = False
        self.modem_comm_lock = threading.Lock()
        self.initialisation_lock = threading.Lock()

        try:
            self.session.get(self.home_url, timeout=(0.5, 0.5))
            self.connected = True
        except requests.exceptions.ConnectTimeout as e:
            self.connected = False
            print (e)

    def is_connected(f):
        def wrapper(self, *args, **kwargs):
            if self.connected is False:
                return None

            return f(self, *args, **kwargs)
        return wrapper

    @is_connected
    def _api_request(self, api_method_url):
        strAPITokenLocal = self._get_token()
        headers = {'__RequestVerificationToken': strAPITokenLocal}

        try:
            r = self.session.get(url=self.api_url + api_method_url,headers=headers, allow_redirects=False, timeout=(0.5, 0.5))
        except requests.exceptions.RequestException as e:
            logging.debug('[_api_request] Exception: ' + str(e))
            return False

        if r.status_code != 200:
            logging.debug('[_api_request] r.status_code error: r.status_code = ' + str(r.status_code))
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']
            logging.debug('[_api_request] response error code: ' + self.error_code)
            return False

        resp = xmltodict.parse(r.text).get('response', None)
        if resp is not None:
            self.data = resp
            for key in resp:
                setattr(self, key, resp[key])
##            return True
            return resp

    @is_connected
    def _api_post(self, api_method_url, data):
        self._get_token()
        headers = {'__RequestVerificationToken': self.token}
        request = {}
        request['request'] = data
        try:
            r = self.session.post(url=self.api_url + api_method_url,
                                  data=xmltodict.unparse(request, pretty=True),
                                  headers=headers, timeout=(0.5, 0.5))
        except requests.exceptions.RequestException as e:
            return False

        if r.status_code != 200:
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']
            return False
        return True


    @is_connected
    def _get_token(self):
        api_method_url = 'webserver/SesTokInfo'
        try:
            self.modem_comm_lock.acquire()
            r = self.session.get(url=self.api_url + api_method_url, allow_redirects=False, timeout=(0.5, 0.5))
            self.modem_comm_lock.release()
        except requests.exceptions.RequestException as e:
            self.modem_comm_lock.release()
            logging.debug('_get_token: ' + str(e))
            return self
        except: #catch all exceptions
            self.modem_comm_lock.release()
            logging.debug('_get_token: ' + sys.exc_info()[0])
            return self

        if r.status_code != 200:
            logging.debug('_get_token response error: status_code = ' + str(response.status_code))
            return self
        
        strAPITokenLocal = xmltodict.parse(r.text)['response']['TokInfo']
        if strAPITokenLocal is not None:
            logging.debug('_get_token cliet token: ' + strAPITokenLocal)
        else:
            logging.debug('_get_token Client API token response is empty')
            return self

        self.token = strAPITokenLocal   #legacy code support only, will need to be deleted eventually
        self.api_headers['__RequestVerificationToken'] = strAPITokenLocal   #legacy code support only, will need to be deleted eventually
        return strAPITokenLocal

    def _get_sms_module_token(self):
        try:
            self.modem_comm_lock.acquire()
            response = self.session.get('http://192.168.0.1/html/smsinbox.html', timeout=(0.5,0.5))
            self.modem_comm_lock.release()
        except requests.exceptions.RequestException as e:
            self.modem_comm_lock.release()
            logging.debug('_get_sms_module_token: ' + str(e))
            return self
        except:
            self.modem_comm_lock.release()
            logging.debug('_get_sms_module_token: ' + sys.exc_info()[0])
            return self

        if response.status_code != 200:
            logging.debug('_get_sms_module_token response error: status_code = ' + str(response.status_code))
            return self
        else:
##            logging.debug('_get_sms_module_token XML response: ' + response.text.replace('&nbsp',''))  #DEBUG
            dictXMLResponseContent= xmltodict.parse(response.text.replace('&nbsp',''))['html']['head']['meta']

        #Iterate through response XML content to find the 'csrf_token'
        for item in dictXMLResponseContent:
            if item['@name'] == 'csrf_token':   #the first one is the one we want
                strSMSModuleTokenLocal = item['@content']
                break

        if strSMSModuleTokenLocal is not None:
            logging.debug('_get_sms_module_token client token: ' + strSMSModuleTokenLocal)   #DEBUG
        else:
            logging.debug('_get_sms_module_token FAILED TO FIND SMS MODULE CLIENT TOKEN')
            return self
        
        self.sms_module_headers['__RequestVerificationToken'] = strSMSModuleTokenLocal  #legacy code support only, will need to be removed eventually
        self.sms_module_token = strSMSModuleTokenLocal  #legecy code support only, will need to be removed eventually
        self.sms_module_connected = True
        return strSMSModuleTokenLocal
    
    def _get_error_info(self, errorCode):
        errorCodeMap = {}
        errorCodeMap['-1'] = 'system not available'
        errorCodeMap['100002'] = 'not supported by firmware or incorrect API path'
        errorCodeMap['100003'] = 'unauthorized'
        errorCodeMap['100004'] = 'system busy'
        errorCodeMap['100005'] = 'unknown error'
        errorCodeMap['100006'] = 'invalid parameter'
        errorCodeMap['100009'] = 'write error'
        errorCodeMap['103002'] = 'unknown error'
        errorCodeMap['103015'] = 'unknown error'
        errorCodeMap['108001'] = 'invalid username'
        errorCodeMap['108002'] = 'invalid password'
        errorCodeMap['108003'] = 'user already logged in'
        errorCodeMap['108006'] = 'invalid username or password'
        errorCodeMap['108007'] = 'invalid username, password, or session timeout'
        errorCodeMap['110024'] = 'battery charge less than 50%'
        errorCodeMap['111019'] = 'no network response'
        errorCodeMap['111020'] = 'network timeout'
        errorCodeMap['111022'] = 'network not supported'
        errorCodeMap['113018'] = 'system busy'
        errorCodeMap['113055'] = 'SMS action already completed'
        errorCodeMap['114001'] = 'file already exists'
        errorCodeMap['114002'] = 'file already exists'
        errorCodeMap['114003'] = 'SD card currently in use'
        errorCodeMap['114004'] = 'path does not exist'
        errorCodeMap['114005'] = 'path too long'
        errorCodeMap['114006'] = 'no permission for specified file or directory'
        errorCodeMap['115001'] = 'unknown error'
        errorCodeMap['117001'] = 'incorrect WiFi password'
        errorCodeMap['117004'] = 'incorrect WISPr password'
        errorCodeMap['120001'] = 'voice busy'
        errorCodeMap['125001'] = 'invalid token'
        errorCodeMap['125003'] = 'invalid/expired token'
        return errorCodeMap.get(errorCode, 'n/a')
    
    def _get_connection_status(self, status):
        statu = {}
        statu['2'] = 'Connection failed, the profile is invalid'
        statu['3'] = 'Connection failed, the profile is invalid'
        statu['5'] = 'Connection failed, the profile is invalid'
        statu['8'] = 'Connection failed, the profile is invalid'
        statu['20'] = 'Connection failed, the profile is invalid'
        statu['21'] = 'Connection failed, the profile is invalid'
        statu['23'] = 'Connection failed, the profile is invalid'
        statu['27'] = 'Connection failed, the profile is invalid'
        statu['28'] = 'Connection failed, the profile is invalid'
        statu['29'] = 'Connection failed, the profile is invalid'
        statu['30'] = 'Connection failed, the profile is invalid'
        statu['31'] = 'Connection failed, the profile is invalid'
        statu['32'] = 'Connection failed, the profile is invalid'
        statu['7'] = 'Network access not allowed'
        statu['11'] = 'Network access not allowed'
        statu['14'] = 'Network access not allowed'
        statu['37'] = 'Network access not allowed'
        statu['12'] = 'Connection failed, roaming not allowed'
        statu['13'] = 'Connection failed, bandwidth exceeded'
        statu['201'] = 'Connection failed, bandwidth exceeded'
        statu['900'] = 'Connecting'
        statu['901'] = 'Connected'
        statu['902'] = 'Disconnected'
        statu['903'] = 'Disconnecting'
        statu['904'] = 'Connection failed or disabled'
        return statu.get(status, 'n/a')

    def _get_network_type(self, nt):
        ntype = {}
        ntype['0'] = 'No Service'
        ntype['1'] = 'GSM'
        ntype['2'] = 'GPRS (2.5G)'
        ntype['3'] = 'EDGE (2.75G)'
        ntype['4'] = 'WCDMA (3G)'
        ntype['5'] = 'HSPDA (3G)'
        ntype['6'] = 'HSUPA (3G)'
        ntype['7'] = 'HSPA (3G)'
        ntype['8'] = 'TD-SCDMA (3G)'
        ntype['9'] = 'HSPA+ (4G)'
        ntype['10'] = 'EV-DO rev. 0'
        ntype['11'] = 'EV-DO rev. A'
        ntype['12'] = 'EV-DO rev. B'
        ntype['13'] = '1xRTT'
        ntype['14'] = 'UMB'
        ntype['15'] = '1xEVDV'
        ntype['16'] = '3xRTT'
        ntype['17'] = 'HSPA+ 64QAM'
        ntype['18'] = 'HSPA+ MIMO'
        ntype['19'] = 'LTE (4G)'
        ntype['41'] = 'UMTS (3G)'
        ntype['44'] = 'HSPA (3G)'
        ntype['45'] = 'HSPA+ (3G)'
        ntype['46'] = 'DC-HSPA+ (3G)'
        ntype['64'] = 'HSPA (3G)'
        ntype['65'] = 'HSPA+ (3G)'
        ntype['101'] = 'LTE (4G)'
        return ntype.get(nt, 'n/a')

    def _get_roaming_status(self, status):
        statu = {}
        statu['0'] = 'Disabled'
        statu['1'] = 'Enabled'
        return statu.get(status, 'n/a')

    @is_connected
    def is_hilink(self):
        return self._api_request('device/basic_information')

    @is_connected
    def basic_info(self):
        '''
        <productfamily>LTE</productfamily>
        <classify>hilink</classify>
        <multimode>0</multimode>
        <restore_default_status>1</restore_default_status>
        <sim_save_pin_enable>0</sim_save_pin_enable>
        <devicename>E3372</devicename>
        '''
        self._api_request('device/basic_information')
        return self

    @is_connected
    def module_switch(self):
        '''
        <ussd_enabled>1</ussd_enabled>
        <bbou_enabled>1</bbou_enabled>
        <sms_enabled>1</sms_enabled>
        <sdcard_enabled>0</sdcard_enabled>
        <wifi_enabled>0</wifi_enabled>
        <statistic_enabled>1</statistic_enabled>
        <help_enabled>0</help_enabled>
        <stk_enabled>0</stk_enabled>
        <pb_enabled>1</pb_enabled>
        <dlna_enabled></dlna_enabled>
        <ota_enabled>0</ota_enabled>
        <wifioffload_enabled>0</wifioffload_enabled>
        <cradle_enabled>0</cradle_enabled>
        <multssid_enable>0</multssid_enable>
        <ipv6_enabled>0</ipv6_enabled>
        <monthly_volume_enabled>1</monthly_volume_enabled>
        <powersave_enabled>0</powersave_enabled>
        <sntp_enabled>0</sntp_enabled>
        <encrypt_enabled>1</encrypt_enabled>
        <dataswitch_enabled>0</dataswitch_enabled>
        <poweroff_enabled>0</poweroff_enabled>
        <ecomode_enabled>1</ecomode_enabled>
        <zonetime_enabled>0</zonetime_enabled>
        <localupdate_enabled>0</localupdate_enabled>
        <cbs_enabled>0</cbs_enabled>
        <qrcode_enabled>0</qrcode_enabled>
        <charger_enbaled>0</charger_enbaled>
        '''
        self._api_request('global/module-switch')
        return self

    @is_connected
    def coverged_status(self):
        '''
        <SimState>257</SimState>
        <SimLockEnable>0</SimLockEnable>
        <CurrentLanguage>ru-ru</CurrentLanguage>
        '''
        self._api_request('monitoring/converged-status')
        return self

    @is_connected
    def pin_status(self):
        '''
        <SimState>257</SimState>
        <PinOptState>258</PinOptState>
        <SimPinTimes>3</SimPinTimes>
        <SimPukTimes>10</SimPukTimes>
        '''
        self._api_request('pin/status')
        return self

    @is_connected
    def sim_lock(self):
        '''
        <SimLockEnable>0</SimLockEnable>
        <SimLockRemainTimes>100</SimLockRemainTimes>
        <pSimLockEnable></pSimLockEnable>
        <pSimLockRemainTimes></pSimLockRemainTimes>
        '''
        self._api_request('pin/simlock')
        return self

    @is_connected
    def monitoring_status(self):
        '''
        <ConnectionStatus>901</ConnectionStatus>
        <WifiConnectionStatus></WifiConnectionStatus>
        <SignalStrength></SignalStrength>
        <SignalIcon>5</SignalIcon>
        <CurrentNetworkType>9</CurrentNetworkType>
        <CurrentServiceDomain>3</CurrentServiceDomain>
        <RoamingStatus>0</RoamingStatus>
        <BatteryStatus></BatteryStatus>
        <BatteryLevel></BatteryLevel>
        <BatteryPercent></BatteryPercent>
        <simlockStatus>0</simlockStatus>
        <WanIPAddress>10.115.89.118</WanIPAddress>
        <WanIPv6Address></WanIPv6Address>
        <PrimaryDns>192.168.104.3</PrimaryDns>
        <SecondaryDns>192.168.104.4</SecondaryDns>
        <PrimaryIPv6Dns></PrimaryIPv6Dns>
        <SecondaryIPv6Dns></SecondaryIPv6Dns>
        <CurrentWifiUser></CurrentWifiUser>
        <TotalWifiUser></TotalWifiUser>
        <currenttotalwifiuser>0</currenttotalwifiuser>
        <ServiceStatus>2</ServiceStatus>
        <SimStatus>1</SimStatus>
        <WifiStatus></WifiStatus>
        <CurrentNetworkTypeEx>46</CurrentNetworkTypeEx>
        <maxsignal>5</maxsignal>
        <wifiindooronly>-1</wifiindooronly>
        <wififrequence>0</wififrequence>
        <classify>hilink</classify>
        <flymode>0</flymode>
        <cellroam>0</cellroam>
        <ltecastatus>0</ltecastatus>
        '''
        self._api_request('monitoring/status')
        self.TextConnectionStatus = self._get_connection_status(self.data['ConnectionStatus'])
        self.data['TextConnectionStatus'] = self.TextConnectionStatus
        self.TextCurrentNetworkType = self._get_network_type(self.data['CurrentNetworkType'])
        self.data['TextCurrentNetworkType'] = self.TextCurrentNetworkType
        self.TextRoamingStatus = self._get_roaming_status(self.data['RoamingStatus'])
        self.data['TextRoamingStatus'] = self.TextRoamingStatus
        return self

    @is_connected
    def check_notifications(self):
        '''
        <UnreadMessage>0</UnreadMessage>
        <SmsStorageFull>0</SmsStorageFull>
        <OnlineUpdateStatus>10</OnlineUpdateStatus>
        '''
        self._api_request('monitoring/check-notifications')
        return self

    @is_connected
    def traffic_statistics(self):
        '''
        <CurrentConnectTime>120</CurrentConnectTime>
        <CurrentUpload>549080</CurrentUpload>
        <CurrentDownload>11407740</CurrentDownload>
        <CurrentDownloadRate>368020</CurrentDownloadRate>
        <CurrentUploadRate>10036</CurrentUploadRate>
        <TotalUpload>554013</TotalUpload>
        <TotalDownload>11429698</TotalDownload>
        <TotalConnectTime>3348</TotalConnectTime>
        <showtraffic>1</showtraffic>
        '''
        self._api_request('monitoring/traffic-statistics')
        return self

    @is_connected
    def device_information(self):
        '''
        <DeviceName>E3372</DeviceName>
        <SerialNumber>G4PDW16623003677</SerialNumber>
        <Imei>861821032479591</Imei>
        <Imsi>401015625704899</Imsi>
        <Iccid>8999701560257048991F</Iccid>
        <Msisdn></Msisdn>
        <HardwareVersion>CL2E3372HM</HardwareVersion>
        <SoftwareVersion>22.317.01.00.00</SoftwareVersion>
        <WebUIVersion>17.100.14.02.577</WebUIVersion>
        <MacAddress1>BA:AB:BE:34:00:00</MacAddress1>
        <MacAddress2></MacAddress2>
        <ProductFamily>LTE</ProductFamily>
        <Classify>hilink</Classify>
        <supportmode>LTE|WCDMA|GSM</supportmode>
        <workmode>WCDMA</workmode>
        '''
        self._api_request('device/information')
        return self

    @is_connected
    def current_plmn(self):
        '''
        <State>0</State>
        <FullName>Beeline KZ</FullName>
        <ShortName>Beeline KZ</ShortName>
        <Numeric>40101</Numeric>
        <Rat>2</Rat>
        '''
        self._api_request('net/current-plmn')
        return self

    @is_connected
    def plmn_list(self):
        '''
        <State>0</State>
        <FullName>Beeline KZ</FullName>
        <ShortName>Beeline KZ</ShortName>
        <Numeric>40101</Numeric>
        <Rat>2</Rat>
        '''
        self._api_request('net/plmn-list')
        return self

    @is_connected
    def device_signal(self):
        '''
        <pci></pci>
        <sc></sc>
        <cell_id></cell_id>
        <rsrq></rsrq>
        <rsrp></rsrp>
        <rssi></rssi>
        <sinr></sinr>
        <rscp></rscp>
        <ecio></ecio>
        <psatt>1</psatt>
        <mode>2</mode>
        <lte_bandwidth></lte_bandwidth>
        <lte_bandinfo></lte_bandinfo>
        '''
        self._api_request('device/signal')
        return self

    @is_connected
    def net_mode(self, set=None):
        '''
        <NetworkMode>01</NetworkMode>
        <NetworkBand>3FFFFFFF</NetworkBand>
        <LTEBand>7FFFFFFFFFFFFFFF</LTEBand>
        '''
        if set is None:
            self._api_request('net/net-mode')
            return self

        self._api_post('net/net-mode', set)
        return self

    @is_connected
    def net_mode_list(self, set=None):
        '''
        <AccessList>
        <Access>00</Access>
        <Access>01</Access>
        <Access>02</Access>
        <Access>03</Access>
        </AccessList>
        <BandList>
        <Band>
        <Name>GSM900&#x2F;GSM1800&#x2F;WCDMA BCVIII&#x2F;WCDMA BCI</Name>
        <Value>2000000400380</Value>
        </Band>
        </BandList>
        <LTEBandList>
        <LTEBand>
        <Name>LTE BC1&#x2F;LTE BC3&#x2F;LTE BC7&#x2F;
              LTE BC8&#x2F;LTE BC20</Name>
        <Value>800c5</Value>
        </LTEBand>
        <LTEBand>
        <Name>All bands</Name>
        <Value>7ffffffffffffff</Value>
        </LTEBand>
        </LTEBandList>
        '''
        if set is None:
            self._api_request('net/net-mode-list')
            return self

        self._api_post('net/net-mode-list', set)
        return self

    @is_connected
    def dialup_connection(self, set=None):
        '''
        <RoamAutoConnectEnable>0</RoamAutoConnectEnable>
        <MaxIdelTime>600</MaxIdelTime>
        <ConnectMode>0</ConnectMode>
        <MTU>1500</MTU>
        <auto_dial_switch>1</auto_dial_switch>
        <pdp_always_on>0</pdp_always_on>
        '''
        if set is None:
            self._api_request('dialup/connection')
            return self

        self._api_post('dialup/connection', set)
        return self

    @is_connected
    def retrieveSingleStatusItem(self, statusItem: str):
        try:
##            print('[Modem retrieveSingleStatusItem] statusItem: ' + statusItem)
            return self.SMS_Allbox_MsgCountInfo[statusItem]
        except AttributeError as e:
            logging.debug('[SMS_retrieveSingleStatusItem] ' + str(e))

    @is_connected
    def SMS_Inbox_getMsg(self):
        try:
            self.initialisation_lock.acquire()
            self.SMS_Allbox_MsgCountInfo
            self.initialisation_lock.release()
        except AttributeError as e:
            logging.debug('[SMS_Inbox_getMsg] ' + str(e))
            if self.SMS_Allbox_getMsgCountInfo() == False:
                self.initialisation_lock.release()
                return False
            self.initialisation_lock.release()

        if self.SMS_Allbox_MsgCountInfo['LocalInbox'] == '0':
            logging.info('[SMS_Sentbox_getMSG] SMS Inbox is empty')
            return False

        numSMSInboxPageIndex = 1
        numSMSDisplayPerPage = self.SMS_Allbox_MsgCountInfo['LocalInbox']
        request = ET.Element("request") #<request>
        PageIndex = ET.SubElement(request,"PageIndex") #<PageIndex>'.$page.'</PageIndex>
        ReadCount = ET.SubElement(request,"ReadCount") #<ReadCount>'.$count.'</ReadCount>
        BoxType = ET.SubElement(request,"BoxType") #<BoxType>'.$boxType.'</BoxType>
        SortType = ET.SubElement(request,"SortType") #<SortType>0</SortType>
        Ascending = ET.SubElement(request,"Ascending") #<Ascending>0</Ascending>
        UnreadPreferred = ET.SubElement(request,"UnreadPreferred") #<UnreadPreferred>'.($unreadPreferred ? '1' : '0').'</UnreadPreferred></request>
        PageIndex.text = str(numSMSInboxPageIndex)
        ReadCount.text = str(numSMSDisplayPerPage)
        BoxType.text = '1'
        SortType.text = '0'
        Ascending.text = '0'
        UnreadPreferred.text = '1'
        strGetSMSInboxListXML = ET.tostring(request, 'utf-8', method="xml")
        if self.DEBUG:
            print("\n==================SMSInbox_PostCommand=======================\n")  #DEBUG
            print (strGetSMSInboxListXML)   #DEBUG
            print("\n=============================================================\n")  #DEBUG

        #==========CRITICAL_SECTION:_ONE_REQUEST,_ONE_RESPONSE_AT_A_TIME===============
        strAPITokenLocal = self._get_token()
##        self._get_sms_module_token()  #IF USING sms_module_token, THEN THE SECOND session.post COMMAND MUST BE UNCOMMENTED        
        if type(strAPITokenLocal) == str:   #if self._get_token return a str, then it has successed in obtaining a token
            logging.debug('SMS_Inbox_getMsg self._get_token is Successful: ' + strAPITokenLocal)
            headers = {}
            headers = {'__RequestVerificationToken': strAPITokenLocal}
        else:
            logging.debug('SMS_Inbox_getMsg self._get_token is Failed')
            return False

        try:
            r = self.session.post(url=self.api_url + 'sms/sms-list',data=strGetSMSInboxListXML,headers=headers, timeout=(0.5, 0.5))
##            r = self.session.post(url=self.api_url + 'sms/sms-list',data=strGetSMSInboxListXML,headers=self.sms_module_headers, timeout=(0.5, 0.5))
        except requests.exceptions.RequestException as e:
            logging.debug('[SMS_Inbox_getMsg] ' + str(e))
            return False
        #==============================================================================
        
        if r.status_code != 200:
            loggine.debug('SMS_Inbox_getMsg response.status_code (should be 200): ' + str(r.status_code))
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']  #legacy code support,to be changed to other implementation for error logging or removed
            logging.debug('SMS_Inbox_getMsg ERROR:' + resp['code'])
            return resp['code']
        if self.SMSInboxContent == None:
            self.SMSInboxContent = r.text
        else:
            logging.info('[SMS_Inbox_getMsg] Previous SMS Inbox Content Not Fully Consumed')
        logging.debug('[SMS_Inbox_getMsg] SMS Inbox successfully retrieved')
        return True

    @is_connected
    def SMS_Sentbox_getMsg(self):
        try:
            self.initialisation_lock.acquire()
            self.SMS_Allbox_MsgCountInfo
            self.initialisation_lock.release()
        except AttributeError as e:
            logging.debug('[SMS_Sentbox_getMsg] ' + str(e))
            if self.SMS_Allbox_getMsgCountInfo()== False:
                self.initialisation_lock.release()
                return False
            self.initialisation_lock.release()
            
        if self.SMS_Allbox_MsgCountInfo['LocalOutbox'] == '0':
            logging.info('[SMS_Sentbox_getMSG] SMS Sentbox is empty')
            return False
        
        numSMSOutboxPage = 1
        numSMSDisplayPerPage = self.SMS_Allbox_MsgCountInfo['LocalOutbox']
        request = ET.Element("request") #<request>
        PageIndex = ET.SubElement(request,"PageIndex") #<PageIndex>'.$page.'</PageIndex>
        ReadCount = ET.SubElement(request,"ReadCount") #<ReadCount>'.$count.'</ReadCount>
        BoxType = ET.SubElement(request,"BoxType") #<BoxType>'.$boxType.'</BoxType>
        SortType = ET.SubElement(request,"SortType") #<SortType>0</SortType>
        Ascending = ET.SubElement(request,"Ascending") #<Ascending>0</Ascending>
        UnreadPreferred = ET.SubElement(request,"UnreadPreferred") #<UnreadPreferred>'.($unreadPreferred ? '1' : '0').'</UnreadPreferred></request>
        PageIndex.text = str(numSMSOutboxPage)
        ReadCount.text = str(numSMSDisplayPerPage)
        BoxType.text = '2'
        SortType.text = '0'
        Ascending.text = '0'
        UnreadPreferred.text = '0'
        strGetSMSOutboxListXML = ET.tostring(request, 'utf-8', method="xml")
        if self.DEBUG:
            print("\n==================SMSSentbox_PostCommand=======================\n")    #DEBUG
            print (strGetSMSOutboxListXML)  #DEBUG
            print("\n=============================================================\n")  #DEBUG

        #==========CRITICAL_SECTION:_ONE_REQUEST,_ONE_RESPONSE_AT_A_TIME===============
##        strAPITokenLocal = self._get_sms_module_token()  #IF USING sms_module_token, THEN THE SECOND session.post COMMAND MUST BE UNCOMMENTED
        strAPITokenLocal = self._get_token()
        if type(strAPITokenLocal) == str:   #if self._get_token return a str, then it has successed in obtaining a token
            logging.debug('SMS_Sentbox_getMsg self._get_token is Successful: ' + strAPITokenLocal)
            headers = {}
            headers = {'__RequestVerificationToken': strAPITokenLocal}
        else:
            logging.debug('SMS_Sentbox_getMsg self._get_token is Failed')
            return False
        
        try:
            r = self.session.post(url=self.api_url + 'sms/sms-list',data=strGetSMSOutboxListXML,headers=headers, timeout=(0.5, 0.5))
##            r = self.session.post(url=self.api_url + 'sms/sms-list',data=strGetSMSOutboxListXML,headers=self.sms_module_headers, timeout=(0.5, 0.5))
        except requests.exceptions.RequestException as e:
            logging.debug('[SMS+Sentbox_getMsg]: ' + str(e))
            return False
        #==============================================================================
        
        if r.status_code != 200:
            logging.debug('SMS_Sentbox_getMsg response.status_code (should be 200):' + str(r.status_code))
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']  #legacy code support, to be changed to implemented logging or removed eventually
            logging.debug('[SMS_Sentbox_getMSG]_RESPONDED_ERROR: (' + resp['code'] + ') ' + self._get_error_info(resp['code']))
            return resp['code']
        if self.SMSSentboxContent == None:
            self.SMSSentboxContent = r.text
        else:
            logging.info('[SMS_Sentbox_getMsg] Previous Sentbox Content Not Fully Consumed')
            return False
        logging.debug('[SMS_Sentbox_getMsg] SMS Sentbox content successfully retrieved')
        return True

    def SMS_Inbox_setMsgRead(self, id=None):
        self._get_sms_module_token()
        if id == None:
            return
        request = ET.Element("request")
        Index = ET.SubElement(request,"Index")
        Index.text = id
        strSetSMSMsgReadXML = ET.tostring(request,'utf-8', method="xml")
        if self.DEBUG:
            print("\n==================SMSInbox_SetRead_PostCommand=======================\n")  #DEBUG
            print(strSetSMSMsgReadXML)  #DEBUG
            print("\n=====================================================================\n")  #DEBUG

        headers = {}
        headers['__RequestVerificationToken'] = self.sms_module_token
        try:
            r = self.session.post(url=self.api_url + 'sms/set-read', data = strSetSMSMsgReadXML, headers = headers, timeout=(2, 2))
        except requests.exceptions.ReqeustException as e:
            print (str(e))
            return False

        if r.status_code != 200:
            print ('SMSInbox_SetRead response i!= 200')
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']
            print ('SMSInbox_MsgSetRead ERROR:(' + resp['code'] + ') '+ self._get_error_info(resp['code']))
            return False
        return True

    def SMS_Allbox_getMsgCountInfo(self):
        self._get_sms_module_token()
##        headers = {}
##        headers = {'__RequestVerificationToken': self.sms_module_token}
        try:
            self.modem_comm_lock.acquire()
            r = self.session.get(url=self.api_url + 'sms/sms-count',headers=self.sms_module_headers,timeout=(0.5, 0.5))
            self.modem_comm_lock.release()
        except requests.exceptions.RequestException as e:
            self.modem_comm_lock.release()
            logging.debug('[SMS_Allbox_getMsgCountInfo]: ' + str(e))
            return False
        
        if r.status_code != 200:
            logging.debug('[SMS_Allbox_getMsgCountInfo]: response.status (should be 200) = ' + str(r.status_code))
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']  #legacy code support, to be removed eventually
            logging.debug('[SMS_Allbox_getMsgCountInfo] ERROR#:(' + resp['code']+') '+ self._get_error_info(resp['code']))
            return False

        resp = xmltodict.parse(r.text).get('response', None)
        if resp is not None:
            self.SMS_Allbox_MsgCountInfo = resp
            logging.info("[SMS_Allbox_getMsgCountInfo] successfully ran!")
            logging.debug('[SMS_Allbox_getMsgCountInfo] Allbox SMS Count Info: ' + str(resp))
            self.SMSAllboxMsgCountLastRefreshTime = time.time()
            return self

        logging.debug('[SMS_Allbox_getMsgCountInfo] response content body is empty')
        return False


    @is_connected
    def send_sms(self, set=None):
        self._get_sms_module_token()
        if set is None:
            return
        strPhoneNum = set['PhoneNum']
        strSMSContent = set['Message']
        strCurrentTime = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        headers = {}
        headers['__RequestVerificationToken'] = self.sms_module_token
        #headers['X-Requested-With'] = 'XMLHttpRequest'
        #headers['Content-Type'] = 'text/xml'
        strXMLrequest = '<request><Index>-1</Index><Phones><Phone>' + strPhoneNum + '</Phone></Phones><Sca /><Content>' + strSMSContent
        strXMLrequest = strXMLrequest + '</Content><Length>' + str(len(strSMSContent)) + '</Length><Reserved>1</Reserved><Date>' + strCurrentTime
        strXMLrequest = strXMLrequest + '</Date></request>'
        try:
            r = self.session.post(url=self.api_url + 'sms/send-sms', data=strXMLrequest, headers=headers, timeout=(2, 2))
        except requests.exceptions.RequestException as e:
            print (str(e))
            return False

        if r.status_code != 200:
            print ('SMS_Send response i!= 200')
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']
            print ('[SMS SEND] ERROR:' + self.error_code)
            return False
        return True

    def delete_sms(self, id=None):
        self._get_sms_module_token()
        if id is None:
            return
        request = ET.Element("request");
        Index = ET.SubElement(request,"Index")
        Index.text = id
        strDeleteSMSMsgXML = ET.tostring(request,'utf-8', method="xml")
        headers = {}
        headers['__RequestVerificationToken'] = self.sms_module_token
        try:
            r = self.session.post(url=self.api_url + 'sms/delete-sms', data = strDeleteSMSMsgXML, headers = headers, timeout=(2, 2))
        except requests.exceptions.RequestException as e:
            print (str(e))
            return False

        if r.status_code != 200:
            print ('SMSInbox_SetRead response i!= 200')
            return False

        resp = xmltodict.parse(r.text).get('error', None)
        if resp is not None:
            self.error_code = resp['code']
            print ('SMSInbox_MsgSetRead ERROR:' + self.error_code)
            return False
        return True

    def smsInboxProcessor(self):
        self.SMSInboxList = xmltodict.parse(self.SMSInboxContent)
        for message in self.SMSInboxList['response']['Messages']['Message']:
            senderNum = message['Phone']
            receivedContent = message['Content']
            msgType = message['SmsType']
            msgIndex = message['Index']
            print('From:' + senderNum + ' Message:' + str(receivedContent) + ' Type:' + msgType)
            if msgType == '7':
                print('SMS Inbox setMsgRead: ' + str(self.SMS_Inbox_setMsgRead(msgIndex)))
                print('SMS Inbox delete: ' + str(self.delete_sms(msgIndex)))

    def smsSentboxProcessor(self):
        self.SMSSentboxList = xmltodict.parse(self.SMSSentboxContent)
        if int(self.SMS_Allbox_MsgCountInfo['LocalOutbox']) > 1:
            for message in self.SMSSentboxList['response']['Messages']['Message']:
                print(message.data)
                receipentNum = message['Phone']
                sentContent = message['Content']
                msgType = message['SmsType']
                msgIndex = message['Index']
                print('To: ' + receipentNum + ' Message:' + str(sentContent) + ' Type: ' + msgType)
                if msgType == '1':
                    print('SMS SentMsg delete: ' + str(self.delete_sms(msgIndex)))
        else:
            message = self.SMSSentboxList['response']['Messages']['Message']
            receipentNum = message['Phone']
            sentContent = message['Content']
            msgType = message['SmsType']
            msgIndex = message['Index']
            print('To: ' + receipentNum + ' Message:' + str(sentContent) + ' Type: ' + msgType)
            if msgType == '1':
                print('SMS SentMsg delete: ' + str(self.delete_sms(msgIndex)))
            
