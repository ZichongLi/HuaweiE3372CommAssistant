from E3372h import Client
import threading, time, signal
import xmltodict
import csv
import os.path
import signal
import logging
import sys
import queue
from collections import OrderedDict
from multiprocessing.pool import ThreadPool

dictRelevantPhoneNum = {}
dictAvailableAction = {}
listUserTaskInputSocket = {}

class QueueSpool(queue.Queue):
    def __init__(self, consumer=None, timeout=None, queueLength=None):
        if queueLength == None:
            super().__init__(maxsize=50)
        else:
            super().__init__(maxsize=queueLength)
        if timeout == None:
            self.blockingTimeout = 3
        else:
            self.blockingTimeout = timeout
        
        self.threadEventSpoolRunning = threading.Event()
        self.threadEventSpoolRunning.set()
        self.tcbObj = threading.Thread(target=self.sendFromSpool)
        if consumer == None:
            self.consumer = self.dummyConsumer
        else:
            self.consumer = consumer
        
    def dummyConsumer(item):
        pass
    
    def putMsg(self, item):
        try:    #attempt to put item to spool
            self.put(item, True, self.blockingTimeout)  #block if Queue is full, blocking timeout after 3 seconds
        except queue.Full as e:
            logging.info('[QueueSpoolManager] INPUT: BUFFER IS FULL discarding message: ' + item)
        return

    def getMsg(self, boolOptBlocking: bool, TO: int):   #blocking queue get method
        try:
            return self.get(boolOptBlocking, TO)
        except queue.Empty as e:
            logging.info('[QueueSpoolManager] OUTPUT: BUFFER IS EMPTY ')
        return

    def addToSpool(self, msg):
        self.startConsumerThread()
        self.putMsg(msg)
        return
    
    def sendFromSpool(self):    #the spool(consumer) function will only run as a thread
        while self.threadEventSpoolRunning.is_set():    
            self.consumer(self.getMsg(True, self.blockingTimeout))  #blocking dequeue function that times-out after 3 seconds
            if self.empty():    #if the queue is empty, exit the loop
                break
        self.threadEventSpoolRunning.clear()
        return

    def forceShutdown(self):
        self.threadEventSpoolRunning.clear()    #reset spoolingRunning flag
        self.queue.clear()  #dump all content in queue
        return

    def startConsumerThread(self):
        self.threadEventSpoolRunning.set()
        while self.tcbObj.is_alive() == False:  #try to crank start the consumer thread
            try:
                self.tcbObj.start() #attempt to start the sendFromSpool thread
                logging.info('  [QueueSpool] START THREAD: sendFromSpool')
            except RuntimeError as e:   #fail to start reason: thread is currently executing; or it has been terminated
                if not self.tcbObj.is_alive():  #if the last spawned thread is terminated
                    self.tcbObj.join()  #clean up the leftover from previously terminated thread
                    self.tcbObj = threading.Thread(target=self.sendFromSpool)  #recreate the thread object
                    logging.info('  [QueueSpool] RECREATE THREAD: sendFromSpool')
                else:   #if the last spawned thread is still running
                    pass   #do nothing
        return

class periodicThreadConstructor(threading.Thread):
    def __init__(self, interval, task, *args):
        threading.Thread.__init__(self)
        self.daemon = False
        self.stopSignal = threading.Event()
        self.periodicInterval = interval
        self.periodicTask = task
        self.args = args
##        self.kwargs = kwargs

    def stopPeriodicThread(self):
        self.stopSignal.set()
        self.join()

    def run(self):
        while not self.stopSignal.wait(self.periodicInterval):
            self.periodicTask(*self.args)


class userTaskThreadConstructor(queue.Queue):
    def __init__(self, task, commTimeout, outputSocket, inputQueueLength=None):
        if inputQueueLength == None:
            inputQueueLength = 1
        else:
            pass
        super().__init__(maxsize=inputQueueLength)
        self.commTimeout = commTimeout
        self.tcbUserTask = threading.Thread(target=task,args=(self.userTaskSocket,outputSocket))

    def InputSocket(self, msg): #Input Socket to user thread message queue
        try:    #attempt to put item to spool
            self.put(msg, True, self.commTimeout)  #block if Queue is full, blocking timeout
        except queue.Full as e:
            logging.info('[userTaskThread] INPUT SOCKET: BUFFER IS FULL discarding message: ' + msg)
        return self

    def userTaskSocket(self):   #Output socket to user task function thread
        try:
            return self.get(True, self.commTimeout)
        except queue.Empty as e:
            logging.info('[userTaskThread] USER SOCKET: BUFFER IS EMPTY ')
        return self
    
    def launchAsThread(self):
        self.tcbUserTask.start()
        return self.tcbUserTask


class mdmAllboxMsgCleanup:
    def __init__(self, ModemObj: Client):
        self.ModemObj = ModemObj
        self.msgBoxTypes = ['Outbox','Inbox']
    
    def smsAllboxMsgCleanup(self, MsgSpoolInputSocket: OrderedDict):
        msgBoxType = MsgSpoolInputSocket.pop('InOrOut', None)
        try:
            msgIndex = MsgSpoolInputSocket['Index']
        except:
            e = sys.exc_info()[0]
            logging.debug('[smsAllboxMsgCleanup] dictSMS' + self.msgBoxTypes[msgBoxType] + 'Messages ERROR: ' + e)
        if msgBoxType == 1:
            logging.info('  [smsAllboxMsgCleanup] SMS Inbox setMsgRead: ' + str(self.ModemObj.SMS_Inbox_setMsgRead(msgIndex)))
            SMS_backup2csv(MsgSpoolInputSocket, 'E3372h_InboxSMS_backup.csv') #Save each SMS XML Content to csv file
        else:
            SMS_backup2csv(MsgSpoolInputSocket, 'E3372h_OutboxSMS_backup.csv')   #Save each previous Sent SMS XML content to csv file
        logging.info('  [smsAllboxMsgCleanup] SMS ' + self.msgBoxTypes[msgBoxType] + ' delete: ' + str(self.ModemObj.delete_sms(msgIndex)))
        return

class applicationThreadObjManager(OrderedDict):
    def __init__(self):
        super().__init__()

    def addNewThreadObj(self, strTag=None, userTaskThreadObj=None):
        if userTaskThreadObj == None:
            pass
        elif strTag == None:
            pass
        elif strTag in self:    #if Tag string is already enrolled in the Manager
            pass
        else:
            self[strTag] = userTaskThreadObj
        return
    
    def hasThreadObj(self, strTag):
        return strTag in self
    
    def getThreadObj(self, strTag=None):
        if strTag == None:
            return
        else:
            return self.get(strTag, None)

    def removeNdeallocateThreadObj(self, strTag=None):
        if strTag == None:
            pass
        else:
            self.pop(strTag, None)
        return

class CustomException(Exception):  #this is a custom exception base class
    pass

class shutdown(CustomException):
    pass

def SMS_backup2csv(SMSData: OrderedDict, strBackupFileName):
    fieldNames = ['Smstat', 'Index', 'Phone', 'Content', 'Date', 'Sca', 'SaveType', 'Priority', 'SmsType']
    if len(SMSData) != len(fieldNames):
        raise SmsFormatError
    else:
        for SmsComponent in fieldNames:
            try:
                SMSData[SmsComponent]
            except KeyError as e:
                logging.debug('[SMS_backup2csv] SMSData: ' + str(e))
    if not os.path.isfile(strBackupFileName):
        first_time_open_file = True
    else:
        first_time_open_file = False
    with open(strBackupFileName,'a', newline='') as SMSbackup:
        SMSBackupWriter = csv.DictWriter(SMSbackup, fieldnames = fieldNames, dialect = 'excel')
        if first_time_open_file:
            SMSBackupWriter.writeheader()
            logging.debug('[SMS_backup2csv] File Header Written attempted')
        SMSBackupWriter.writerow(SMSData)

def messageProcessor(message: OrderedDict, userThreadsManager, msgOutPort):
    logging.info('[messageProcessor] RUNNING') 
    if userThreadsManager.hasThreadObj(message['Phone']): #inspect for thread object in the manager
        if userThreadsManager.getThreadObj(message['Phone']).tcbUserTask.is_alive():    #and thread is alive
            userThreadsManager.getThreadObj(message['Phone']).InputSocket(message['Content'])   #send message down user task input socket
            logging.info('[messageProcessor] sent: <' + message['Content'] + '> to ' + message['Phone'])
            return
        else:
            pass
    logging.info('[messageProcessor] constructing new thread')
    newUserTaskThreadObj = userTaskThreadConstructor(dummyUserTaskOne, 6, msgOutPort, 2)    #new user thread witha 6sec TO input 2 elmt deep queue
    userThreadsManager.removeNdeallocateThreadObj(message['Phone'])
    userThreadsManager.addNewThreadObj(message['Phone'],newUserTaskThreadObj)
    userThreadsManager.getThreadObj(message['Phone']).InputSocket(message['Content'])
    newUserTaskThreadObj.launchAsThread()
    return

def smsMsgForwarder(message: OrderedDict, msgForwarder=None):
    strForwardMsg = 'From: '+ message['Phone'] + '||Content: ' + message['Content']
    dictRecomposedMsg = {'PhoneNum':'XXXXXXXXXX','Message': strForwardMsg}  # Replace XXXXXXXXXX with a cellphone number
    if msgForwarder == None:
        logging.info('Unspecified Message: ' + strForwardMsg)
    else:
        msgForwarder(dictRecomposedMsg)
    return


def smsInboxProcessor(dictSMSInboxContent: OrderedDict, ModemObj: Client, appThreadManager, msgOutPort, outSocket1):
    if int(dictSMSInboxContent['response']['Count']) == 0:
        logging.info('[smsInboxProcessor] SMS Inbox is empty, no need to continue')
        return
    elif int(dictSMSInboxContent['response']['Count']) > 1:
        dictSMSInboxMessages = dictSMSInboxContent['response']['Messages']['Message']
    else:
        dictSMSInboxMessages = [dictSMSInboxContent['response']['Messages']['Message']]

    logging.debug('[smsInboxProcessor] dictSMSInboxMessages = ' + str(dictSMSInboxMessages))

    for message in dictSMSInboxMessages:
        try:
            senderNum = message['Phone']
            receivedContent = message['Content']
            msgType = message['SmsType']
            msgIndex = message['Index']
        except:
            e = sys.exc_info()[0]
            logging.debug('[smsInboxProcessor] dictSMSInboxMessages ERROR: ' + e)
        message['InOrOut'] = 1
        outSocket1(message) #output socket to message cleanup task
        print('From:' + senderNum + ' Message:' + str(receivedContent) + ' Type:' + msgType)
        if msgType == '7':  #automatic receipt confirmation sms reply
            pass
        elif len(senderNum) == 3:    #network operator sent sms
            if msgType == '2' and senderNum == '128':
                message['Content'] = 'Voicemail Alert, check voicemail'
            elif receivedContent == None:
                message['Content'] = 'Unkown Network Message'
            else:  
                smsMsgForwarder(message, msgOutPort)                    #MESSAGE FORWARDING FUNCTION
        elif senderNum == '+1XXXXXXXXXX' or senderNum == 'XXXXXXXXXX':  # Replace XXXXXXXXXX with valid cellphone number NOTE: some time a phone number will show up with +1 in front of the phone number.
            messageProcessor(message, appThreadManager, msgOutPort)     # FUTURE LOCATION FOR MESSAGE PROCESSOR
        else:
            smsMsgForwarder(message, msgOutPort)    #MESSAGE FORWARDING FUNCTION

def smsSentboxProcessor(dictSMSOutboxContent: OrderedDict, ModemObj: Client, outSocket1):
    if int(dictSMSOutboxContent['response']['Count']) == 0:
        logging.info('[smsSentboxProcessor] The SMS Outbox is empty, no need to continue.')
        return
    elif int(dictSMSOutboxContent['response']['Count']) > 1:
        dictSMSOutboxMessages = dictSMSOutboxContent['response']['Messages']['Message']
    else:
        dictSMSOutboxMessages = [dictSMSOutboxContent['response']['Messages']['Message']]
    logging.debug('dictSMSOutboxMessages = ' + str(dictSMSOutboxMessages))
    for message in dictSMSOutboxMessages:
        try:
            receipentNum = message['Phone']
            sentContent = message['Content']
            msgType = message['SmsType']
            msgIndex = message['Index']
        except: #catch all exceptions
            e = sys.exc_info()[0]   #fetch the latest exception message
            logging.info('[smsSentboxProcessor] dictSMSOutboxMessages ERRPR: ' + e)
        print('To: ' + receipentNum + ' Message:' + str(sentContent) + ' Type: ' + msgType)
        message['InOrOut'] = 0
        outSocket1(message)


def smsInboxProcessingTask(ModemObj: Client, appThreadManager, msgOutPort, outSocket1):
    timeElapsedSinceLastUpdate = time.time() - ModemObj.SMSAllboxMsgCountLastRefreshTime
    if timeElapsedSinceLastUpdate > 5:
        ModemObj.SMS_Allbox_getMsgCountInfo()
    else:
        pass
    strSMSInboxGetMsgResp = ModemObj.SMS_Inbox_getMsg()
    if type(strSMSInboxGetMsgResp) == str:  #if the return is a string, then it is a ERROR code generated by the modem
        return strSMSInboxGetMsgResp
    elif type(strSMSInboxGetMsgResp) == bool:
        if strSMSInboxGetMsgResp == True:
            try:
                smsInboxProcessor(xmltodict.parse(ModemObj.SMSInboxContent),ModemObj, appThreadManager, msgOutPort, outSocket1)
                ModemObj.SMSInboxContent = None
            except AttributeError as e:
                logging.debug('[main-->smsInboxProcessor] ' + str(e))
        else:
            logging.info('[main-->smsInboxProcessor] ModemObj.SMS_Inbox_getMsg encountered error in fetching latest Inbox Content')
    else:
        pass
    return

def smsOutboxProcessingTask(ModemObj: Client, outSocket1):
    timeElapsedSinceLastUpdate = time.time() - ModemObj.SMSAllboxMsgCountLastRefreshTime
    if timeElapsedSinceLastUpdate > 5:
        ModemObj.SMS_Allbox_getMsgCountInfo()
    else:
        pass
    strSMSOutboxGetMsgResp = ModemObj.SMS_Sentbox_getMsg()
    if type(strSMSOutboxGetMsgResp) == str:
        return strSMSOutboxGetMsgResp
    elif type(strSMSOutboxGetMsgResp) == bool:
        if strSMSOutboxGetMsgResp == True:
            try:
                smsSentboxProcessor(xmltodict.parse(ModemObj.SMSSentboxContent),ModemObj, outSocket1)
                ModemObj.SMSSentboxContent = None
            except AttributeError as e:
                logging.debug('[main-->smsSentboxProcessor] ' + str(e))
        else:
            logging.info('[main-->smsSentboxProcessor] ModemObj.SMS_Outbox_getMsg encountered error in fetching latest Sentbox Content')
    else:
        pass
    return

def shutdownCleanup(signum, frame):
    logging.info("  Shutdown Initiated")
    raise shutdown

def dummyAction(cmd):
    pass
    
def dummyUserTaskOne(inputSocket, outputSocket):
    global dictAvailableAction
    actionMsg = inputSocket()
    logging.info('[dummyUserTaskOne] action message received: ' + actionMsg)
    numUnreadSMSCount = dictAvailableAction.get(actionMsg, dummyAction)('LocalUnread')
    print('[dummyUserTaskOne] ' + numUnreadSMSCount)
    dictOutgoingMessage = {'PhoneNum':'XXXXXXXXXX','Message':'Unread SMS Count:'+numUnreadSMSCount} #Replace XXXXXXXXXX with a valid cellphone number
    outputSocket(dictOutgoingMessage)
    return
    
def main():
    global dictAvailableAction
    global dictRelevantPhoneNum
    c = Client()
    dictRelevantPhoneNum['+1XXXXXXXXXX'] = True                 #Replace +1XXXXXXXXXX with a valid cellphone number
    dictAvailableAction['Total Unread'] = c.retrieveSingleStatusItem
    userTaskThreadsManager = applicationThreadObjManager()    #manages user task listening port and/or (thread information)
    smsOutputManager = QueueSpool(c.send_sms)
    mdmMsgboxJanitor = mdmAllboxMsgCleanup(c)
    smsAllboxMsgQueue = QueueSpool(mdmMsgboxJanitor.smsAllboxMsgCleanup)
    if c.is_hilink():
        # print c.basic_info().productfamily
        # print c.net_mode().NetworkMode
##        print c.plmn_list().data
##        dictAllNotifications = c.check_notifications().data
##        print (c.current_plmn().data)   #DEBUG
##        print (c.monitoring_status().data)  #DEBUG
        signal.signal(signal.SIGINT, shutdownCleanup)
        listTCB = list()
        taskOne = periodicThreadConstructor(4, task=c.current_plmn)
        listTCB.append(taskOne)
        taskTwo = periodicThreadConstructor(3, task=c.monitoring_status)
        listTCB.append(taskTwo)
        taskThree = periodicThreadConstructor(5, smsInboxProcessingTask, c, userTaskThreadsManager, smsOutputManager.addToSpool,smsAllboxMsgQueue.addToSpool)
        listTCB.append(taskThree)
        taskFour = periodicThreadConstructor(5, smsOutboxProcessingTask, c,smsAllboxMsgQueue.addToSpool)
        listTCB.append(taskFour)
        print ('Thread Control Block List Length: ' + str(len(listTCB)))
        for tcbElmt in listTCB:
            tcbElmt.start()

        print(c.data)
        while True:
            try:
                time.sleep(1)
            except shutdown:
                break
            
        for tcbElmt in listTCB:
            tcbElmt.stopPeriodicThread()
        try:
            smsOutputManager.tcbObj.join()
        except RuntimeError as e:
            if smsOutputManager.tcbObj.is_alive() == False:
                logging.info('[smsOutputManager(QueueSpool)] SMS Output Spool was not used')
            else:
                logging.info('[smsOutputManager(QueueSpool)] ' + str(e))
        try:
            smsAllboxMsgQueue.tcbObj.join()
        except RuntimeError as e:
            if smsAllboxMsgQueue.tcbObj.is_alive() == False:
                logging.info('[smsAllboxMsgQueue(QueueSpool)] SMS post-processing modem cleanup queue was not used')
            else:
                logging.info('[smsAllboxMsgQueue(QueueSpool)] ' + str(e))
        return

       #  if c.SMS_Inbox_getMsg():
       #      logging.debug(c.SMSInboxContent)   #DEBUG
       #      dictSMSInbox = xmltodict.parse(c.SMSInboxContent)
       #      logging.debug(dictSMSInbox['response']['Count']) #DEBUG
       #      smsInboxProcessor(dictSMSInbox,c)
       #  else:
       #      print('SMS Inbox Retrieval Failure')
       #  if c.SMS_Sentbox_getMsg():
       #      print('\n============Sentbox_Content:SMSSentboxContent==============\n')    #DEBUG
       #      print(c.SMSSentboxContent)  #DEBUG
       #      dictSMSSentbox = xmltodict.parse(c.SMSSentboxContent)   #DEBUG
       #      print(dictSMSSentbox['response']['Messages']['Message'])    #DEBUG
       #      print('\n===========================================================\n')    #DEBUG
       #      c.smsSentboxProcessor()
       #  else:
       #      print('SMS Sentbox Retrieval Failure')
       #  numUnreadSMSCount = c.SMS_Allbox_MsgCountInfo['LocalUnread']
       #  if c.send_sms({'PhoneNum':'XXXXXXXXXX','Message':'Unread SMS Count:'+numUnreadSMSCount}): #Replace XXXXXXXXXX with a valid cellphone number
       #      print ('success')
       #  else:
       #      print ('failure')
	# pass
        # print c.module_switch().ussd_enabled
        # dialup_connection = c.dialup_connection()
        # print dialup_connection.ConnectMode
        # print dialup_connection.data
        # d = dialup_connection.data
        # d['ConnectMode'] = 0
        # d['MaxIdelTime'] = 1200
        # print d
        # c.dialup_connection(set=d)
if __name__ == "__main__":
    format = "%(asctime)s: %(message)s"
    logging.basicConfig(format=format, level=logging.INFO, datefmt="%H:%M:%S")
    #logging.getLogger().setLevel(logging.INFO)
    main()
