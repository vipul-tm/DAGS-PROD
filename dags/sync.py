import os
import socket
from airflow import DAG
from airflow.contrib.hooks import SSHHook
from airflow.operators import PythonOperator
from airflow.operators import BashOperator
from airflow.operators import BranchPythonOperator
from airflow.hooks.mysql_hook import MySqlHook
from airflow.hooks import RedisHook
from airflow.hooks.mysql_hook import MySqlHook
from datetime import datetime, timedelta	
from airflow.models import Variable
from airflow.operators import TriggerDagRunOperator
from airflow.operators.subdag_operator import SubDagOperator
from pprint import pprint
from copy import deepcopy
import itertools
import socket
import sys
import time
import re
import random
import logging
import traceback
import os
import json


#################################################################DAG CONFIG####################################################################################

default_args = {
	'owner': 'wireless',
	'depends_on_past': False,
	'start_date': datetime(2017, 03, 30,13,00),
	'email': ['vipulsharma144@gmail.com'],
	'email_on_failure': False,
	'email_on_retry': False,
	'retries': 1,
	'retry_delay': timedelta(minutes=1),
	'provide_context': True,
	# 'queue': 'bash_queue',
	# 'pool': 'backfill',
	# 'priority_weight': 10,
	# 'end_date': datetime(2016, 1, 1),
	 
}
PARENT_DAG_NAME = "SYNC"
main_etl_dag=DAG(dag_id=PARENT_DAG_NAME, default_args=default_args, schedule_interval='@once')
SQLhook=MySqlHook(mysql_conn_id='application_db')
redis_hook_2 = RedisHook(redis_conn_id="redis_hook_2")
#################################################################FUCTIONS####################################################################################
def get_host_ip_mapping():
	path = Variable.get("hosts_mk_path")
	try:
		host_var = load_file(path)
		ipaddresses = host_var.get('ipaddresses')
		return ipaddresses 
	except IOError:
		logging.error("File Name not correct")
		return None
	except Exception:
		logging.error("Please check the HostMK file exists on the path provided ")
		traceback.print_exc()
		return None

def remove_duplicates(input_list):
	newlist = []
	for i in input_list:
		if i not in newlist:
			newlist.append(i)

	return newlist

def load_file(file_path):
	#Reset the global vars
	host_vars = {
		"all_hosts": [],
		"ipaddresses": {},
		"host_attributes": {},
		"host_contactgroups": [],
	}
	try:
		execfile(file_path, host_vars, host_vars)
		del host_vars['__builtins__']
	except IOError, e:
		pass
	return host_vars


def process_host_mk():
	path = Variable.get("hosts_mk_path")
	hosts = {}
	site_mapping = {}
	all_site_mapping =[]
	all_list = []
	device_dict = {}
	start = 0
	tech_wise_device_site_mapping = {}
	try:
		text_file = open(path, "r")
		
	except IOError:
		logging.error("File Name not correct")
		return "notify"
	except Exception:
		logging.error("Please check the HostMK file exists on the path provided ")
		return "notify"

	lines = text_file.readlines()
	host_ip_mapping = get_host_ip_mapping()
	for line in lines:
		if "all_hosts" in line:
	  		start = 1

		if start == 1:
			hosts["hostname"] = line.split("|")[0]
			hosts["device_type"] = line.split("|")[1]
			site_mapping["hostname"] = line.split("|")[0].strip().strip("'")
			
			site_mapping['site'] = line.split("site:")[1].split("|")[0].strip()  

			site_mapping['device_type'] = line.split("|")[1].strip()
		   
			all_list.append(hosts.copy())
			all_site_mapping.append(site_mapping.copy())
			if ']\n' in line:
				start = 0
				all_list[0]['hostname'] = all_list[0].get("hostname").strip('all_hosts += [\'')
				all_site_mapping[0] ['hostname'] = all_site_mapping[0].get("hostname").strip('all_hosts += [\'')
				break
	print "LEN of ALL LIST is %s"%(len(all_list))
	if len(all_list) > 1:
	   	for device in all_list:
	  		device_dict[device.get("hostname").strip().strip("'")] = device.get("device_type").strip()
		Variable.set("hostmk.dict",str(device_dict))

		for site_mapping in all_site_mapping:
			if site_mapping.get('device_type') not in  tech_wise_device_site_mapping.keys():				
				tech_wise_device_site_mapping[site_mapping.get('device_type')] = {site_mapping.get('site'):[{"hostname":site_mapping.get('hostname'),"ip_address":host_ip_mapping.get(site_mapping.get('hostname'))}]}
			else:
				if site_mapping.get('site') not in  tech_wise_device_site_mapping.get(site_mapping.get('device_type')).keys():
					tech_wise_device_site_mapping.get(site_mapping.get('device_type'))[site_mapping.get('site')] = [{"hostname":site_mapping.get('hostname'),"ip_address":host_ip_mapping.get(site_mapping.get('hostname'))}]
				else:
					tech_wise_device_site_mapping.get(site_mapping.get('device_type')).get(site_mapping.get('site')).append({"hostname":site_mapping.get('hostname'),"ip_address":host_ip_mapping.get(site_mapping.get('hostname'))})

		Variable.set("hostmk.dict.site_mapping",str(tech_wise_device_site_mapping))
		count = 0 
		for x in tech_wise_device_site_mapping:
			for y in tech_wise_device_site_mapping.get(x):
				count = count+len(tech_wise_device_site_mapping.get(x).get(y))\

		print "COUNT : %s"%(count)
		return 0
	else:
		return -4

def dict_rows(cur):
	desc = cur.description
	return [
		dict(zip([col[0] for col in desc], row))
		for row in cur.fetchall()
	]


def execute_query(query):
	conn = SQLhook.get_conn()
	cursor = conn.cursor()
	cursor.execute(query)
	data =  dict_rows(cursor)
	cursor.close()
	return data

def createDict(data):
	#TODOL There are 3 levels of critality handle all those(service_critical,critical,dtype_critical)
	rules = {}
	ping_rule_dict = {}
	operator_name_with_operator_in = eval(Variable.get("special_operator_services")) #here we input the operator name in whcih we wish to apply IN operator
	service_name_with_operator_in = []
	for operator_name in operator_name_with_operator_in:
		service_name = "_".join(operator_name.split("_")[:-1])
		service_name_with_operator_in.append(service_name)


	for device in data:
		service_name = device.get('service')
		device_type = device.get('devicetype')
		if device.get('dtype_ds_warning') and device.get('dtype_ds_critical'):
			device['critical'] = device.get('dtype_ds_critical')
			device['warning'] = device.get('dtype_ds_warning')
		elif device.get('service_warning') and device.get('service_critical'):
			device['critical'] = device.get('service_critical')
			device['warning'] = device.get('service_warning')
		

		if service_name == 'radwin_uas' and device['critical'] == "":
			continue
			
		if service_name:
			name =  str(service_name)
			rules[name] = {}
		if device.get('critical'):
			rules[name]={"Severity1":["critical",{'name': str(name)+"_critical", 'operator': 'greater_than' if ("_rssi"  not in name) and ("_uas"  not in name) else "less_than_equal_to", 'value': device.get('critical') or device.get('dtype_ds_critical')}]}
		else:
			rules[name]={"Severity1":["critical",{'name': str(name)+"_critical", 'operator': 'greater_than', 'value': ''}]}
		if device.get('warning'):
			rules[name].update({"Severity2":["warning",{'name': str(name)+"_warning", 'operator': 'greater_than' if ("_rssi"  not in name) and ("_uas"  not in name) else "less_than_equal_to" , 'value': device.get('warning') or device.get('dtype_ds_warning')}]})
		else:
			rules[name].update({"Severity2":["warning",{'name': str(name)+"_warning", 'operator': 'greater_than', 'value': ''}]})
		if device_type not in ping_rule_dict:
			if device.get('ping_pl_critical') and device.get('ping_pl_warning') and device.get('ping_rta_critical') and device.get('ping_rta_warning'):
				 ping_rule_dict[device_type] = {
				'ping_pl_critical' : device.get('ping_pl_critical'),
				'ping_pl_warning': 	 device.get('ping_pl_warning') ,
				'ping_rta_critical': device.get('ping_rta_critical'),
				'ping_rta_warning':  device.get('ping_rta_warning')
				}
	for device_type in  ping_rule_dict:
		if ping_rule_dict.get(device_type).get('ping_pl_critical'):
			rules[device_type+"_pl"]={}
			rules[device_type+"_pl"].update({"Severity1":["critical",{'name': device_type+"_pl_critical", 'operator': 'greater_than', 'value': float(ping_rule_dict.get(device_type).get('ping_pl_critical')) or ''}]})
			
		if ping_rule_dict.get(device_type).get('ping_pl_warning'):
			rules[device_type+"_pl"].update({"Severity2":["warning",{'name': device_type+"_pl_warning", 'operator': 'greater_than', 'value': float(ping_rule_dict.get(device_type).get('ping_pl_warning')) or ''}]})
			rules[device_type+"_pl"].update({"Severity3":["up",{'name': device_type+"_pl_up", 'operator': 'less_than', 'value': float(ping_rule_dict.get(device_type).get('ping_pl_warning')) or ''},'AND',{'name': device_type+"_pl_up", 'operator': 'greater_than_equal_to', 'value': 0}]})
			rules[device_type+"_pl"].update({"Severity4":["down",{'name': device_type+"_pl_down", 'operator': 'equal_to', 'value': 100}]})
			
		if ping_rule_dict.get(device_type).get('ping_rta_critical'):
			rules[device_type+"_rta"] = {}
			rules[device_type+"_rta"].update({"Severity1":["critical",{'name': device_type+"_rta_critical", 'operator': 'greater_than', 'value': float(ping_rule_dict.get(device_type).get('ping_rta_critical')) or ''}]})
		if ping_rule_dict.get(device_type).get('ping_rta_warning'):
			rules[device_type+"_rta"].update({"Severity2":["warning",{'name': device_type+"_rta_warning", 'operator': 'greater_than', 'value': float(ping_rule_dict.get(device_type).get('ping_rta_warning')) or ''}]})
			rules[device_type+"_rta"].update({"Severity3":["up",{'name': device_type+"_rta_up", 'operator': 'less_than', 'value': float(ping_rule_dict.get(device_type).get('ping_rta_warning'))},'AND',{'name': device_type+"_rta_up", 'operator': 'greater_than', 'value': 0 }]})
			
			#TODO: This is a seperate module should be oneto prevent re-looping ovver rules
	for rule in rules:
		if rule in set(service_name_with_operator_in):
			#service_name = "_".join(rule.split("_")[0:4])
			service_rules = rules.get(rule)
			for i in range(1,len(service_rules)+1):		
				severities = service_rules.get("Severity%s"%i)
				for x in range(1,len(severities),2):
					if severities[x].get("name") in operator_name_with_operator_in.keys():
						severities[x]["operator"] = operator_name_with_operator_in.get(severities[x].get("name"))

	return rules

def process_kpi_rules(all_services_dict):
	#TODO Update this code for both ul_issue and other KPIS
	kpi_rule_dict = {}
	formula_mapper = eval(Variable.get('ul_issue_kpi_to_formula_mapping'))
	kpi_services_mapper = eval(Variable.get('ul_issue_services_mapping'))
	kpi_services_mapper = eval(Variable.get('provision_services_mapping'))
	formula_mapper = eval(Variable.get('provision_kpi_to_formula_mapping'))
	util_mapper = eval(Variable.get('utilization_kpi_attributes'))
	
	for service in all_services_dict.keys():
		if "util_kpi" in service:
			try:
				
				device_type = ""
				for device_type_loop in formula_mapper:
					if service in formula_mapper.get(device_type_loop):
						device_type = device_type_loop
	
				kpi_services = kpi_services_mapper.get(device_type)
		
				kpi_rule_dict[service] = {
				"name":service,
				"isFunction":False,
				"formula":"calculate_%s_utilization"%(service),
				"isarray":[False,False],
				"service":kpi_services,
				"arraylocations":0
				}
			except Exception:
				print service
				traceback.print_exc()
				continue
	print  kpi_rule_dict

	return kpi_rule_dict

def generate_service_rules():

	service_threshold_query = Variable.get('q_get_thresholds')
	#creating Severity Rules
	data = execute_query(service_threshold_query)
	rules_dict = createDict(data)
	Variable.set("rules",str(rules_dict))

#can only be done if generate_service_rules is completed and there is a rule Variable in Airflow Variables
def generate_kpi_rules():

	service_rules = eval(Variable.get('rules'))
	processed_kpi_rules = process_kpi_rules(service_rules)
	#Variable.set("kpi_rules",str(processed_kpi_rules))

def generate_kpi_prev_states():
	ul_tech = eval(Variable.get('ul_issue_kpi_technologies'))
	old_pl_data = redis_hook_2.get("all_devices_state")
	all_device_type_age_dict = {}
	for techs_bs in ul_tech:		
		redis_hook_2.set("kpi_ul_prev_state_%s"%(ul_tech.get(techs_bs)),old_pl_data)
		redis_hook_2.set("kpi_ul_prev_state_%s"%(techs_bs),old_pl_data)

def generate_backhaul_inventory_for_util():
	backhaul_inventory_data_query="""
	select
	device_device.ip_address,
	device_device.device_name,
	device_devicetype.name,
	device_device.mac_address,
	device_devicetype.agent_tag,
	site_instance_siteinstance.name,
	device_device.device_alias,
	device_devicetechnology.name as techno_name,
	group_concat(service_servicedatasource.name separator '$$') as port_name,
	group_concat(inventory_basestation.bh_port_name separator '$$') as port_alias,
	group_concat(inventory_basestation.bh_capacity separator '$$') as port_wise_capacity
	from device_device
	inner join
	(device_devicetechnology, device_devicetype,
	machine_machine, site_instance_siteinstance)
	on
	(
	device_devicetype.id = device_device.device_type and
	device_devicetechnology.id = device_device.device_technology and
	machine_machine.id = device_device.machine_id and
	site_instance_siteinstance.id = device_device.site_instance_id
	)
	inner join
	(inventory_backhaul)
	on
	(device_device.id = inventory_backhaul.bh_configured_on_id OR device_device.id = inventory_backhaul.aggregator_id OR
	 device_device.id = inventory_backhaul.pop_id OR
	 device_device.id = inventory_backhaul.bh_switch_id OR
	 device_device.id = inventory_backhaul.pe_ip_id)
	left join
	(inventory_basestation)
	on
	(inventory_backhaul.id = inventory_basestation.backhaul_id)
	left join
	(service_servicedatasource)
	on
	(inventory_basestation.bh_port_name = service_servicedatasource.alias)
	where
	device_device.is_deleted=0 and
	device_device.host_state <> 'Disable'
	and
	device_devicetype.name in ('Cisco','Juniper','RiCi', 'PINE','Huawei','PE')
	group by device_device.ip_address;	
	"""
	switch_query="select device_device.device_name, site_instance_siteinstance.name, device_device.ip_address, device_devicetype.name, device_devicetechnology.name as techno_name, group_concat(service_servicedatasource.name separator '$$') as port_name, group_concat(inventory_basestation.bh_port_name separator '$$') as port_alias, group_concat(inventory_basestation.bh_capacity separator '$$') as port_wise_capacity from device_device inner join (device_devicetechnology, device_devicetype, machine_machine, site_instance_siteinstance) on ( device_devicetype.id = device_device.device_type and device_devicetechnology.id = device_device.device_technology and machine_machine.id = device_device.machine_id and site_instance_siteinstance.id = device_device.site_instance_id ) inner join (inventory_backhaul) on (device_device.id = inventory_backhaul.bh_configured_on_id OR device_device.id = inventory_backhaul.aggregator_id OR device_device.id = inventory_backhaul.pop_id OR device_device.id = inventory_backhaul.bh_switch_id) left join (inventory_basestation) on (inventory_backhaul.id = inventory_basestation.backhaul_id) left join (service_servicedatasource) on (inventory_basestation.bh_port_name = service_servicedatasource.alias) where device_device.is_deleted=0 and device_device.host_state <> 'Disable' and device_devicetype.name in ('RiCi', 'PINE') group by device_device.ip_address;".strip()
	
	backhaul_query = """
	select
	bh_device.device_name,
	site_instance_siteinstance.name,
	bh_device.ip_address,
	dtype.name as device_type,
	GROUP_CONCAT(bs.bh_port_name separator ',') as bh_ports,
	GROUP_CONCAT(sds.name separator ',') as service_alias,
	group_concat(bs.bh_capacity separator ',') as port_wise_capacity 
	from
	inventory_basestation as bs
	left join
	inventory_backhaul as bh
	on
	bs.backhaul_id = bh.id
	left join
	device_device as bh_device
	ON
	bh_device.id = bh.bh_configured_on_id
	left join
	device_devicetype as dtype
	ON
	dtype.id = bh_device.device_type
	left join
	service_servicedatasource as sds
	ON
	lower(sds.name) = lower(bs.bh_port_name)
	OR
	lower(sds.alias) = lower(bs.bh_port_name)
	OR
	lower(sds.name) = lower(replace(bs.bh_port_name, '/', '_'))
	OR
	lower(sds.alias) = lower(replace(bs.bh_port_name, '/', '_'))
	left join 
	(machine_machine,site_instance_siteinstance)
	on
	(
	machine_machine.id = bh_device.machine_id and site_instance_siteinstance.id = bh_device.site_instance_id
	)
	WHERE
	lower(dtype.name) in ('juniper', 'cisco','huawei')
	group by
	bh_device.id;
    """
	#backhaul_data = execute_query(backhaul_inventory_data_query)

	backhaul_query_data = execute_query(backhaul_query)
	converter_query_data = execute_query(switch_query)
	print "Length Recieved BH: %s SW:%s"%(len(backhaul_query_data),len(converter_query_data))
	all_data={}
	bh_cap_mappng = {}
	backhaul_cap_mappng = {}
	backhaul_cap_mappng_list = []
	converter_cap_mapping = {}
	converter_cap_mapping_list = []
	all_capacity_list = []
	for b_device in backhaul_query_data:
		dev_name = b_device.get('device_name')
		 
		backhaul_cap_mappng[b_device.get('device_name')] = {
		 'port_name' : filter(None,b_device.get('bh_ports').split(",")) if b_device.get('bh_ports') else None,
		 'port_wise_capacity': filter(None,b_device.get('port_wise_capacity').split(",")) if b_device.get('port_wise_capacity') else None,
		 'ip_address':b_device.get('ip_address'),
		 'port_alias':filter(None,b_device.get('service_alias').split(",")) if b_device.get('service_alias') else None,
		 'capacity': {},
		 'name':dev_name
		 }

		for index,port in enumerate(backhaul_cap_mappng.get(dev_name).get("port_name")):
		 	if len(b_device.get("port_wise_capacity")) == 1:
		 		capacity = b_device.get("port_wise_capacity")
		 		backhaul_cap_mappng.get(dev_name).get("capacity").update({port:capacity})
		 	else:
		 		capacity = b_device.get("port_wise_capacity")
		 		backhaul_cap_mappng.get(dev_name).get("capacity").update({port:capacity})

		all_data[dev_name] = backhaul_cap_mappng.get(dev_name).copy()
		backhaul_cap_mappng_list.append(backhaul_cap_mappng.copy())

	print "TOTAL Device processes %s"%(len(backhaul_cap_mappng_list))

	for b_device in converter_query_data:
		dev_name = b_device.get('device_name')
		 
		converter_cap_mapping[dev_name] = {
		 'port_name' : filter(None,b_device.get('port_name').split(",")) if b_device.get('port_name') else None,
		 'port_wise_capacity': filter(None,b_device.get('port_wise_capacity').split(",")) if b_device.get('port_wise_capacity') else None,
		 'ip_address':b_device.get('ip_address'),
		 'port_alias':filter(None,b_device.get('port_alias').split(",")) if b_device.get('port_alias') else None,
		 'capacity': {},
		 'name':dev_name
		 }
		if converter_cap_mapping.get(dev_name).get("port_name") and converter_cap_mapping.get(dev_name).get("port_name") != None:
			for index,port in enumerate(converter_cap_mapping.get(dev_name).get("port_name")):
			 	if len(b_device.get("port_wise_capacity")) == 1:
			 		capacity = b_device.get("port_wise_capacity")
			 		converter_cap_mapping.get(dev_name).get("capacity").update({port:capacity})
			 	else:
			 		capacity = b_device.get("port_wise_capacity")
			 		converter_cap_mapping.get(dev_name).get("capacity").update({port:capacity})

		all_data[dev_name] = converter_cap_mapping.get(dev_name).copy()
		converter_cap_mapping_list.append(converter_cap_mapping.copy())

	backhaul_cap_mappng_list.extend(converter_cap_mapping_list)
	
	print backhaul_cap_mappng_list[0:10],type(backhaul_cap_mappng_list[0])


	print "FINAL LENGTH --> %s %s"%(len(all_data.keys()),type(all_data))
	#print backhaul_cap_mappng_list
	#print ("FINAL LENGTH : %s"%(len(all_data.keys())))
	# print "TOTAL Device processes %s"%(len(backhaul_cap_mappng_list))

	# print "BH --> Prev %s: Now:%s CON: ---- > Prev: %s Now: %s  "%(len(backhaul_query_data),len(backhaul_cap_mappng_list),len(converter_query_data),len(converter_cap_mapping_list))























	# for device in backhaul_data:
	# 	dev_name = device.get('device_name')
		 
	# 	bh_cap_mappng[device.get('device_name')] = {
	# 	 'port_name' : filter(None,device.get('port_name').split(",")) if device.get('port_name') else None,
	# 	 'port_wise_capacity': filter(None,device.get('port_wise_capacity').split("$$")) if device.get('port_wise_capacity') else None,
	# 	 'ip_address':device.get('ip_address'),
	# 	 'port_alias':filter(None,device.get('port_alias').split("$$")) if device.get('port_alias') else None,
	# 	 'capacity': {}
	# 	 }






	# 	for name_and_alias in ['port_alias','port_name']:
			
	# 		if device.get(name_and_alias) and device.get('port_wise_capacity'):
	# 			for  index,port in enumerate(remove_duplicates(bh_cap_mappng.get(device.get('device_name')).get(name_and_alias))):				
					
	# 				port_capacity = None
	# 				ports=[]
	# 				try:
	# 					if "," in port:
	# 						ports.extend(port.split(','))
	# 					else:
	# 						ports.append(port)

	# 					port_capacity = bh_cap_mappng.get(device.get('device_name')).get('port_wise_capacity')[index]
	# 				except IndexError:
	# 					logging.error("Error Encounterd while assigning for %s"%(device.get('device_name')))
	# 					logging.error(bh_cap_mappng.get(device.get('device_name')).get(name_and_alias))
	# 				except Exception:
	# 					logging.error("GeneralException Encounterd while assigning for %s"%(device.get('device_name')))
	# 					port_capacity = bh_cap_mappng.get(device.get('device_name')).get('port_wise_capacity')[0]



	# 				for port in ports:
	# 					port=port.strip()
						
	# 					if port not in bh_cap_mappng.get(device.get('device_name')).get('capacity').keys():
	# 		 				bh_cap_mappng.get(device.get('device_name')).get('capacity').update({port:port_capacity})

	

	# print "Setting redis Key backhaul_capacities with backhaul capacities "
	# #for dev in bh_cap_mappng:
	# #bh_cap_mappng.get('10561').get('capacity').update({'GigabitEthernet0_0_25':'100','GigabitEthernet0_0_26':'100'})
	# #bh_cap_mappng.get('11389').get('capacity').update({'GigabitEthernet0_0_24':'44'})
	
	# #print bh_cap_mappng

	# for dev in bh_cap_mappng:
		
	# 	try:
	# 		cap=bh_cap_mappng.get(dev).get('port_wise_capacity')
	# 		p_alias = bh_cap_mappng.get(dev).get('port_alias')
	# 		p_name =bh_cap_mappng.get(dev).get('port_name')  if bh_cap_mappng.get(dev).get('port_name') != None else []
	# 		if (len(cap) == len(p_name)) or (len(cap) == len(p_alias)):
	# 			for index,port_alias in enumerate(p_alias):
	# 				try:
	# 					if "," in port_alias:
	# 						alias_ports_after_split = port_alias.split(",")
	# 						for port_spitted in alias_ports_after_split:
	# 							bh_cap_mappng.get(dev).get('capacity').update({port_spitted:cap[index]})
	# 					else:		
	# 						bh_cap_mappng.get(dev).get('capacity').update({port_alias:cap[index]})
	# 						bh_cap_mappng.get(dev).get('capacity').update({p_name[index]:cap[index]})
	# 				except Exception:
	# 					print "EXCEPTION ---> 1"
	# 					pprint(bh_cap_mappng.get(dev))
	# 					print "==============================="
	# 					continue
	# 		else :
	# 			if len(cap) ==1 and len(port_alias) == 2:
	# 				bh_cap_mappng.get(dev).get('capacity').update({p_alias[0]:cap[0]})
	# 				bh_cap_mappng.get(dev).get('capacity').update({p_alias[1]:cap[0]})
	# 			elif len(cap) ==1 and len(port_name) == 2:
	# 				backhaul_cap_mappng.get(dev).get('capacity').update({port_name[0]:cap[0]})
	# 				bh_cap_mappng.get(dev).get('capacity').update({port_name[1]:cap[0]})
	# 			else:
	# 				print "------------------------------------------"
	# 				pprint(bh_cap_mappng.get(dev))
	# 				print "------------------------------------------"
				
	# 	except Exception:
	# 		print  "++++++++++++++++++++++++++++++++++"
	# 		pprint(bh_cap_mappng.get(dev))
	# 		traceback.print_exc()
	# 		print "+++++++++++++++++++++++++++++++++++"


	# print bh_cap_mappng.get('12478').get('capacity')
	# bh_cap_mappng.get('10157').get('capacity')['GigabitEthernet0/0/24'] = '28'
	# bh_cap_mappng.get('10157').get('capacity')['GigabitEthernet0_0_24'] = '28'
	# bh_cap_mappng.get('12478').get('capacity')['ge-0_1_2'] = '1000'
	# bh_cap_mappng.get('12478').get('capacity')['ge-0/1/2'] = '1000'
	# print bh_cap_mappng.get('12478').get('capacity')

	redis_hook_2.set("backhaul_capacities",str(all_data))
	
	print "Successfully Created Key: backhaul_capacities in Redis. "




def generate_basestation_inventory_for_util():
	basestation_inventory_data_query="""
	select
	DISTINCT(device_device.ip_address),
	device_device.device_name,
	device_devicetype.name,
	device_device.mac_address,
	device_device.ip_address,
 	device_devicetype.agent_tag,
	inventory_sector.name,
	site_instance_siteinstance.name,
	device_device.device_alias,
	device_devicetechnology.name as techno_name,
	inventory_circuit.qos_bandwidth as QoS_BW
	from device_device

	inner join
	(device_devicetechnology, device_devicemodel, device_devicetype, machine_machine, site_instance_siteinstance, inventory_sector)
	on
	(
	device_devicetype.id = device_device.device_type and
	device_devicetechnology.id = device_device.device_technology and
	device_devicemodel.id = device_device.device_model and
	machine_machine.id = device_device.machine_id and
	site_instance_siteinstance.id = device_device.site_instance_id and
	inventory_sector.sector_configured_on_id = device_device.id
	)

	left join (inventory_circuit)
	on (
	inventory_sector.id = inventory_circuit.sector_id
	)

	where device_device.is_deleted=0
	and
	device_device.host_state <> 'Disable'
	and
	device_devicetechnology.name in ('WiMAX', 'P2P', 'PMP')
	and
	device_devicetype.name in ('Radwin2KBS', 'CanopyPM100AP', 'CanopySM100AP', 'StarmaxIDU', 'Radwin5KBS','Cambium450iAP');
	"""

	basestation_data = execute_query(basestation_inventory_data_query)
	
	bh_cap_mappng = {}
	for device in basestation_data:
		bh_cap_mappng[device.get('device_name')] = {		 
		 'qos_bandwidth': device.get('QoS_BW') if device.get('QoS_BW') else None,
		 'ip_address':device.get('ip_address'),
		 }

	print "Setting redis Key basestation_capacities with basestation capacities "
	#for dev in bh_cap_mappng:
	#	print bh_cap_mappng.get(dev).get('capacity')
	redis_hook_2.set("basestation_capacities",str(bh_cap_mappng))
	print "Successfully Created Key: basestation_capacities in Redis. "

##################################################################TASKS#########################################################################3
create_devicetype_mapping_task = PythonOperator(
	task_id="generate_host_devicetype_mapping",
	provide_context=False,
	python_callable=process_host_mk,
	#params={"redis_hook_2":redis_hook_2},
	dag=main_etl_dag)
create_severity_rules_task = PythonOperator(
	task_id="generate_service_rules",
	provide_context=False,
	python_callable=generate_service_rules,
	#params={"redis_hook_2":redis_hook_2},
	dag=main_etl_dag)
create_kpi_rules_task = PythonOperator(
	task_id="generate_kpi_rules",
	provide_context=False,
	python_callable=generate_kpi_rules,
	#params={"redis_hook_2":redis_hook_2},
	dag=main_etl_dag)

create_kpi_prev_states = PythonOperator(
	task_id="generate_kpi_previous_states",
	provide_context=False,
	python_callable=generate_kpi_prev_states,
	#params={"redis_hook_2":redis_hook_2},
	dag=main_etl_dag)

generate_backhaul_data = PythonOperator(
	task_id="generate_backhaul_inventory",
	provide_context=False,
	python_callable=generate_backhaul_inventory_for_util,
	#params={"table":"nocout_24_09_14"},
	dag=main_etl_dag)

generate_basestation_data = PythonOperator(
	task_id="generate_basestation_inventory",
	provide_context=False,
	python_callable=generate_basestation_inventory_for_util,
	#params={"table":"nocout_24_09_14"},
	dag=main_etl_dag)




##################################################################END#########################################################################3

