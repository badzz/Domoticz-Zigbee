#!/usr/bin/env python3
# coding: utf-8 -*-
#
# Author: zaraki673 & pipiche38
#
"""
    Module: z_output.py

    Description: All communications towards Zigate

"""

import Domoticz
import binascii
import struct
import json

from datetime import datetime
from time import time

from Modules.basicOutputs import  send_zigatecmd_zcl_noack
from Modules.bindings import bindDevice

from Modules.zigateConsts import MAX_LOAD_ZIGATE, CFG_RPT_ATTRIBUTESbyCLUSTERS , ZIGATE_EP
from Modules.tools import getClusterListforEP, mainPoweredDevice, \
    check_datastruct, is_time_to_perform_work, set_isqn_datastruct, set_status_datastruct, set_timestamp_datastruct, is_attr_unvalid_datastruct, reset_attr_datastruct
from Modules.logging import loggingConfigureReporting

MAX_ATTR_PER_REQ = 3

def processConfigureReporting( self, NWKID=None ):
    '''
    processConfigureReporting( self )
    Called at start of the plugin to configure Reporting of all connected object, based on their corresponding cluster

    Synopsis:
    - for each Device
        if they support Cluster we want to configure Reporting 

    '''

    now = int(time())
    if NWKID is None :
        if self.busy or self.ZigateComm.loadTransmit() > MAX_LOAD_ZIGATE:
            loggingConfigureReporting( self, 'Debug2', "configureReporting - skip configureReporting for now ... system too busy (%s/%s) for %s"
                  %(self.busy, self.ZigateComm.loadTransmit(), NWKID), nwkid=NWKID)
            return # Will do at the next round
        target = list(self.ListOfDevices.keys())
        clusterlist = None
    else:
        target = []
        target.append(NWKID)

    for key in target:
        # Let's check that we can do a Configure Reporting. Only during the pairing process (NWKID is provided) or we are on the Main Power
        if key == '0000': 
            continue

        if key not in self.ListOfDevices:
            Domoticz.Error("processConfigureReporting - Unknown key: %s" %key)
            continue

        if 'Status' not in self.ListOfDevices[key]:
            Domoticz.Error("processConfigureReporting - no 'Status' flag for device %s !!!" %key)
            continue

        if self.ListOfDevices[key]['Status'] != 'inDB': 
            continue

        if NWKID is None:
            if not mainPoweredDevice(self, key):
                continue    #  Not Main Powered!

            if 'Health' in self.ListOfDevices[key]:
                if self.ListOfDevices[key]['Health'] == 'Not Reachable':
                    continue

            #if self.ListOfDevices[key]['Model'] != {}:
            #    if self.ListOfDevices[key]['Model'] == 'TI0001': # Livolo switch
            #        continue

        cluster_list = CFG_RPT_ATTRIBUTESbyCLUSTERS
        if 'Model' in self.ListOfDevices[key]:
            if self.ListOfDevices[key]['Model'] != {}:
                if self.ListOfDevices[key]['Model'] in self.DeviceConf:
                    if 'ConfigureReporting' in self.DeviceConf[ self.ListOfDevices[key]['Model'] ]:
                        spec_cfgrpt = self.DeviceConf[ self.ListOfDevices[key]['Model'] ]['ConfigureReporting']
                        cluster_list = spec_cfgrpt
                        loggingConfigureReporting( self, 'Debug2', "------> CFG_RPT_ATTRIBUTESbyCLUSTERS updated: %s --> %s" %(key, cluster_list), nwkid=key)

        loggingConfigureReporting( self, 'Debug2', "----> configurereporting - processing %s" %key, nwkid=key)

        manufacturer = "0000"
        manufacturer_spec = "00"
        direction = "00"
        addr_mode = "02"

        for Ep in self.ListOfDevices[key]['Ep']:
            loggingConfigureReporting( self, 'Debug2', "------> Configurereporting - processing %s/%s" %(key,Ep), nwkid=key)
            clusterList = getClusterListforEP( self, key, Ep )
            loggingConfigureReporting( self, 'Debug2', "------> Configurereporting - processing %s/%s ClusterList: %s" %(key,Ep, clusterList), nwkid=key)
            for cluster in clusterList:
                if cluster in ( 'Type', 'ColorMode', 'ClusterType' ):
                    continue
                if cluster not in cluster_list:
                    continue
                if 'Model' in self.ListOfDevices[key]:
                    if  self.ListOfDevices[key]['Model'] != {}:
                        if self.ListOfDevices[key]['Model'] == 'lumi.light.aqcn02':
                            if cluster in ( '0402', '0403', '0405', '0406'):
                                continue
                        if self.ListOfDevices[key]['Model'] == 'lumi.remote.b686opcn01' and Ep != '01':
                            # We bind only on EP 01
                            loggingConfigureReporting( self, 'Debug',"Do not Configure Reporting lumi.remote.b686opcn01 to Zigate Ep %s Cluster %s" %(Ep, cluster), key)
                            continue
                
                # Bad Hack for now. FOR PROFALUX
                if self.ListOfDevices[key]['ProfileID'] == '0104':
                    if self.ListOfDevices[key]['ZDeviceID'] == '0201': # Remote
                        # Do not Configure Reports Remote Command
                        loggingConfigureReporting( self, 'Debug',"----> Do not Configure Reports cluster %s for Profalux Remote command %s/%s" %(cluster, key, Ep), key)
                        continue

                loggingConfigureReporting( self, 'Debug2', "--------> Configurereporting - processing %s/%s - %s" %(key,Ep,cluster), nwkid=key)

                if not is_time_to_perform_work(self, 'ConfigureReporting', key, Ep, cluster, now, (21 * 3600) ):
                    loggingConfigureReporting( self, 'Debug', "--------> Not time to perform  %s/%s - %s" %(key,Ep,cluster), nwkid=key)
                    continue

                if NWKID is None and (self.busy or self.ZigateComm.loadTransmit() > MAX_LOAD_ZIGATE):
                    loggingConfigureReporting( self, 'Debug', "---> configureReporting - %s skip configureReporting for now ... system too busy (%s/%s) for %s"
                        %(key, self.busy, self.ZigateComm.loadTransmit(), key), nwkid=key)
                    return # Will do at the next round

                loggingConfigureReporting( self, 'Debug', "---> configureReporting - requested for device: %s on Cluster: %s" %(key, cluster), nwkid=key)

                # If NWKID is not None, it means that we are asking a ConfigureReporting for a specific device
                # Which happens on the case of New pairing, or a re-join
                if self.pluginconf.pluginConf['allowReBindingClusters'] and NWKID is None:
                    # Correctif 22 Novembre. Delete only for the specific cluster and not the all Set
                    if 'Bind' in self.ListOfDevices[key]:
                        if Ep in self.ListOfDevices[key]['Bind']:
                            if cluster in self.ListOfDevices[key]['Bind'][ Ep ]:
                                del self.ListOfDevices[key]['Bind'][ Ep ][ cluster ]
                    if 'IEEE' in self.ListOfDevices[key]:
                        loggingConfigureReporting( self, 'Debug', "---> configureReporting - requested Bind for %s on Cluster: %s" %(key, cluster), nwkid=key)
                        bindDevice( self, self.ListOfDevices[key]['IEEE'], Ep, cluster )
                    else:
                        Domoticz.Error("configureReporting - inconsitency on %s no IEEE found : %s " %(key, str(self.ListOfDevices[key])))

                set_timestamp_datastruct(self, 'ConfigureReporting', key, Ep, cluster, int(time()) )

                attrDisp = []   # Used only for printing purposes
                attrList = ''
                attrLen = 0
                if 'Attributes' not in cluster_list[cluster]:
                    continue

                for attr in cluster_list[cluster]['Attributes']:
                    # Check if the Attribute is listed in the Attributes List (provided by the Device
                    # In case Attributes List exists, we have git the list of reported attribute.
                    if cluster == '0300': 
                        # We need to evaluate the Attribute on ZDevice basis
                        if self.ListOfDevices[key]['ZDeviceID'] == {}:
                            continue

                        ZDeviceID = self.ListOfDevices[key]['ZDeviceID']
                        if 'ZDeviceID' in  cluster_list[cluster]['Attributes'][attr]:
                            if ZDeviceID not in cluster_list[cluster]['Attributes'][attr]['ZDeviceID'] and \
                                    len( cluster_list[cluster]['Attributes'][attr]['ZDeviceID'] ) != 0:
                                loggingConfigureReporting( self, 'Debug',"configureReporting - %s/%s skip Attribute %s for Cluster %s due to ZDeviceID %s" %(key,Ep,attr, cluster, ZDeviceID), nwkid=key)
                                continue
                   
                    forceAttribute = False

                    if 'Attributes List' in self.ListOfDevices[key] and not forceAttribute:
                        if 'Ep' in self.ListOfDevices[key]['Attributes List']:
                            if Ep in self.ListOfDevices[key]['Attributes List']['Ep']:
                                if cluster in self.ListOfDevices[key]['Attributes List']['Ep'][Ep]:
                                    if attr not in self.ListOfDevices[key]['Attributes List']['Ep'][Ep][cluster]:
                                        loggingConfigureReporting( self, 'Debug', "configureReporting: drop attribute %s" %attr, nwkid=key)
                                        continue

                    if int(self.FirmwareVersion,16) <= int('31c',16):
                        if is_attr_unvalid_datastruct( self, 'ConfigureReporting', key, Ep, cluster , '0000' ):
                            continue
                        reset_attr_datastruct( self, 'ConfigureReporting', key, Ep, cluster , '0000' )
                        
                    if int(self.FirmwareVersion,16) > int('31c',16):
                        if is_attr_unvalid_datastruct( self, 'ConfigureReporting', key, Ep, cluster , attr ):
                            continue
                        reset_attr_datastruct( self, 'ConfigureReporting', key, Ep, cluster , attr )


                    if self.pluginconf.pluginConf['breakConfigureReporting']:
                        # Sending Configur Reporting Attribute One by One
                        attrdirection = "00"
                        attrType = cluster_list[cluster]['Attributes'][attr]['DataType']
                        minInter = cluster_list[cluster]['Attributes'][attr]['MinInterval']
                        maxInter = cluster_list[cluster]['Attributes'][attr]['MaxInterval']
                        timeOut =  cluster_list[cluster]['Attributes'][attr]['TimeOut']
                        chgFlag =  cluster_list[cluster]['Attributes'][attr]['Change']
                        attrList = attrdirection + attrType + attr + minInter + maxInter + timeOut + chgFlag
                        attrLen = 1
                        loggingConfigureReporting( self, 'Debug', "Configure Reporting %s/%s on cluster %s" %(key, Ep, cluster), nwkid=key)
                        loggingConfigureReporting( self, 'Debug', "-->  Len: %s Attribute List: %s" %(attrLen, attrList), nwkid=key)
                        #datas =   addr_mode + key + ZIGATE_EP + Ep + cluster + direction + manufacturer_spec + manufacturer 
                        datas =   ZIGATE_EP + Ep + cluster + direction + manufacturer_spec + manufacturer 
                        datas +=  "%02x" %(attrLen) + attrList
                        loggingConfigureReporting( self, 'Debug', "configureReporting - 0120 - %s" %(datas))
                        send_zigatecmd_zcl_noack( self, key, '0120', datas )
                        #sendZigateCmd(self, "0120", datas )
                    else:
                        # The Command will be issued when out of the loop and all Attributes seens
                        attrDisp.append(attr)
                        loggingConfigureReporting( self, 'Debug', "    Configure Reporting %s/%s Cluster %s Adding attr: %s " %(key, Ep, cluster, attr), nwkid=key)
                # end of For attr

                # Ready to send the Command in one shoot or in several.
                attributeList = []
                attrList = ''
                attrLen = 0
                if not self.pluginconf.pluginConf['breakConfigureReporting']:
                    for attr in attrDisp:
                        attrdirection = "00"
                        attrType = cluster_list[cluster]['Attributes'][attr]['DataType']
                        minInter = cluster_list[cluster]['Attributes'][attr]['MinInterval']
                        maxInter = cluster_list[cluster]['Attributes'][attr]['MaxInterval']
                        timeOut =  cluster_list[cluster]['Attributes'][attr]['TimeOut']
                        chgFlag =  cluster_list[cluster]['Attributes'][attr]['Change']
                        attributeList.append( attr )
                        attrList += attrdirection + attrType + attr + minInter + maxInter + timeOut + chgFlag
                        attrLen += 1

                        # Let's check if we have to send a chunk
                        if attrLen == MAX_ATTR_PER_REQ:
                            # Prepare the payload
                            #datas =   addr_mode + key + ZIGATE_EP + Ep + cluster + direction + manufacturer_spec + manufacturer 
                            datas =   ZIGATE_EP + Ep + cluster + direction + manufacturer_spec + manufacturer 

                            datas +=  "%02x" %(attrLen) + attrList

                            loggingConfigureReporting( self, 'Debug', "configureReporting - Splitting in several parts" )
                            loggingConfigureReporting( self, 'Debug', "--> configureReporting - 0120 - %s" %(datas))
                            loggingConfigureReporting( self, 'Debug', "--> Configure Reporting %s/%s on cluster %s Len: %s Attribute List: %s" %(key, Ep, cluster, attrLen, attrList), nwkid=key)
                            
                            i_sqn = send_zigatecmd_zcl_noack( self, key, '0120', datas )

                            for x in attributeList:
                                set_isqn_datastruct(self, 'ConfigureReporting', key, Ep, cluster, x, i_sqn )
    
                            #Reset the Lenght to 0
                            attrList = ''
                            attrLen = 0
                            del attributeList
                            attributeList = []
                    # end for 

                    # Let's check if we have some remaining to send
                    if attrLen != 0 :
                        # Prepare the payload
                        #datas =   addr_mode + key + ZIGATE_EP + Ep + cluster + direction + manufacturer_spec + manufacturer 
                        datas =   ZIGATE_EP + Ep + cluster + direction + manufacturer_spec + manufacturer 
                        datas +=  "%02x" %(attrLen) + attrList

                        loggingConfigureReporting( self, 'Debug', "configureReporting - last parts" )
                        loggingConfigureReporting( self, 'Debug', "++> configureReporting - 0120 - %s" %(datas))
                        loggingConfigureReporting( self, 'Debug', "++> Configure Reporting %s/%s on cluster %s Len: %s Attribute List: %s" %(key, Ep, cluster, attrLen, attrList), nwkid=key)
                        i_sqn = send_zigatecmd_zcl_noack( self, key, '0120', datas )
                        for x in attributeList:
                            set_isqn_datastruct(self, 'ConfigureReporting', key, Ep, cluster, x, i_sqn )
                            

            # End for Cluster
        # End for Ep
    # End for key