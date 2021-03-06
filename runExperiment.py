from utils.openstack.UtilSwift import *
from utils.openstack.ConnectionGetter import *
from utils.openstack.UtilSahara import *
from utils.openstack.UtilKeystone import *
from utils.openstack.UtilNova import *
from utils.experiment.JsonParser import *

import os
import sys
import subprocess
import time
import getpass
from subprocess import Popen, call, PIPE

MIN_NUM_ARGS = 7
DEF_CLUSTER_NAME = "test-experiment-cluster"
HDFS_BASE_DIR = "/user/hadoop/"
HOME_INSTANCE_DIR = "/home/hadoop"
DEF_OUTPUT_CONTAINER_NAME = "output"
DEF_INPUT_DIR = "input"
DEF_INPUT_SIZE = 28672
DEF_JOB_NAME = "tarciso-experiment-job-"
OUTPUT_FILE_HEADER = "job_name;job_id;num_reduces;input_size;cluster_size;proc_time;status"

def configureInstances(instancesIps, publicKeyPairPath, privateKeyPairPath):
	print "Configuring Instances..."
	for instanceIp in instancesIps:
        	commandArray = ["./SSHWithoutPassword.sh", instanceIp , publicKeyPairPath, privateKeyPairPath] 
        	command = ' '.join(commandArray)
        	print command
        	call(command,shell=True)
        	print "Configured instance with IP:", instanceIp

def copyFileToInstances(filePath,instancesIps,keypairPath):
    print "Copying " + filePath +" file to instances"
    for instanceIp in instancesIps:
        commandArray = ["scp","-i",keypairPath,"-r",filePath,"hadoop@"+instanceIp+ ':'+HOME_INSTANCE_DIR]
        command = ' '.join(commandArray)
        print command
        call(command,shell=True)
        print "Copied file to instance with IP:", instanceIp

def putFileInHDFS(file_name, masterIp, server_id, keypairPath):
    connection['nova'].attach_volume(server_id, volume_id)
    time.sleep(2)
    print file_name
    remoteFilePath = file_name
    commandArray = ["ssh -i",keypairPath,"hadoop@" + masterIp, "'cat | python -", remoteFilePath, DEF_INPUT_DIR + "'", "<", "./putFileInHDFS.py"]
    command = ' '.join(commandArray)
    print command
    call(command,shell=True)
    connection['nova'].detache_volume(server_id, volume_id)

    print "Success! File is now at HDFS of cluster!"

def createOutputSwiftDataSource(container_out_name,user,password):
	exec_date = datetime.now().strftime('%Y%m%d_%H%M%S')
	output_ds_name ="output_%s_exp_%s" % (user, exec_date)
	container_out_url = "swift://%s.sahara/%s" % (container_out_name, output_ds_name)
	data_source_out = connection['sahara'].createDataSource(output_ds_name,
	    container_out_url,
	    "swift",
	    container_out_name,
	    user,
            password)

	return data_source_out.id

def createHDFSDataSource(name,path):
	print "Creating Data Source in HDFS with name = " + name + " and path = " + path
	return connection['sahara'].createDataSource(name,
				path,
				"hdfs").id

def get_command(master_ip, request):
    command = 'ssh hadoop@%s %s' % (master_ip, request)
    p_status = Popen(command, shell=True, stdout=PIPE,stderr=PIPE)
    status_output, err = p_status.communicate()
    return status_output.strip()

def get_hadoop_job_id(master_ip):
    list_jobs_call = "/opt/hadoop/bin/hadoop job -list | grep 'hadoop' | awk '{print $1}'"
    command = 'ssh hadoop@%s %s' % (master_ip, list_jobs_call)
    p_list_jobs = Popen(command, shell=True, stdout=PIPE,stderr=PIPE)
    list_jobs_output, list_jobs_err = p_list_jobs.communicate()
    job_ids = list_jobs_output.split('\n')
    print job_ids
    for job_id in job_ids:
        if not 'launcher' in job_id:
            return job_id
    return ''

def saveJobResult(job_res,cluster_size,master_ip,num_reduces,job_num,output_file):
	print job_res
	job_name = DEF_JOB_NAME + str(job_num)
	result = ";".join((job_name,job_res['id'], str(num_reduces), str(DEF_INPUT_SIZE), str(cluster_size), str(job_res['time']), job_res['status'])) + "\n"
	print result
	print "Finished"
	f = open(output_file, 'ab')
	f.write(result)
	f.close()

def deleteHDFSFolder(keypairPath, masterIp):
	commandArray = ["ssh -i",keypairPath,"hadoop@" + masterIp, "'cat | python - '", "<", "./removeOutputFile.py"]
	command = ' '.join(commandArray)
	print command
	call(command,shell=True)


def getConnection(user, password, project_name, project_id, main_ip):

    result = {}

    connector = ConnectionGetter(user, password, project_name, project_id, main_ip)

    keystone = UtilKeystone(connector.keystone())
    token_ref_id = keystone.getTokenRef(user, password, project_name).id

    sahara = UtilSahara(connector.sahara(token_ref_id))

    nova = UtilNova(connector.nova())

    result['keystone'] = keystone
    result['sahara'] = sahara
    result['nova'] = nova

    return result

def printUsage():
	print "python runExperiment.py <numberExecs> <mapperExecCmd> <reducerExecCmd> <numReduceTasks> <configFilePath> <outputFile>"

if (len(sys.argv) < MIN_NUM_ARGS):
	print "Wrong number of arguments: ", len(sys.argv)
	printUsage()
	exit(1)

#------------ CONFIGURATIONS -----------------
number_execs = int(sys.argv[1])
mapper_exec_cmd = sys.argv[2]
reducer_exec_cmd = sys.argv[3]
mapred_reduce_tasks = sys.argv[4]
config_file_path = sys.argv[5]
output_file = sys.argv[6]

user = raw_input('OpenStack User: ')
password = getpass.getpass(prompt='OpenStack Password: ')

json_parser = JsonParser(config_file_path)

main_ip = json_parser.get('main_ip')

project_name = json_parser.get('project_name')
project_id = json_parser.get('project_id')

output_container_name = json_parser.get('output_container_name')

job_template_id = json_parser.get('job_template_id')
exec_local_path = json_parser.get('exec_local_path')
public_keypair_path = json_parser.get('public_keypair_path')
private_keypair_path = json_parser.get('private_keypair_path')
private_keypair_name = json_parser.get('private_keypair_name')
input_file_path = json_parser.get('input_file_path')
input_ds_id = json_parser.get('input_ds_id')

net_id = json_parser.get('net_id')
image_id = json_parser.get('image_id')
volume_id = json_parser.get('volume_id')


#------------ WRITING OUTPUT FILE HEADER -----------------
f = open(output_file, 'ab')
f.write(OUTPUT_FILE_HEADER)
f.close()

#------------ GETTING CONNECTION WITH OPENSTACK -----------------
connection = getConnection(user, password, project_name, project_id, main_ip)

#----------------------- EXECUTING EXPERIMENT ------------------------------
job_number = 0
for cluster_template in json_parser.get('cluster_templates'):
	
	cluster_template_id = cluster_template['id']
	cluster_size = cluster_template['n_slaves']
	cluster_input = cluster_template['input_file']
	cluster_name = DEF_CLUSTER_NAME + '-' +  str(cluster_size)

	######### CREATING CLUSTER #############
	try:
		cluster_id = connection['sahara'].createClusterHadoop(cluster_name, image_id, cluster_template_id, net_id, private_keypair_name)
		#cluster_id = "fceab9c1-6b0e-4ff6-b3d0-52418ae91bb4"
	except RuntimeError as err:
		print err.args
		break
		
	######### CONFIGURING CLUSTER ##########
	instancesIps = connection['sahara'].get_instances_ips(cluster_id)
	configureInstances(instancesIps, public_keypair_path, private_keypair_path)
	copyFileToInstances(exec_local_path, instancesIps, private_keypair_path)
	master_ip = connection['sahara'].get_master_ip(cluster_id)
	server_id = connection['sahara'].get_master_id(cluster_id)
	putFileInHDFS(cluster_input, master_ip, server_id, private_keypair_path)

	######### RUNNING JOB ##########
	numSucceededJobs = 0
	while (numSucceededJobs < number_execs):
		job_number += 1
		
		try:
			######### CREATING DATASOURCES ##########
			exec_date = datetime.now().strftime('%Y%m%d_%H%M%S')
			output_hdfs_name ="output_%s_exp_%s" % (user, exec_date) 
			output_ds_id = createHDFSDataSource(output_hdfs_name,HDFS_BASE_DIR + "/" + output_hdfs_name)

			#job_params = { 'mapred.max.split.size' : '1024'}
			job_res = connection['sahara'].runStreamingJob(job_template_id, cluster_id, mapper_exec_cmd, reducer_exec_cmd, input_ds_id=input_ds_id, output_ds_id=output_ds_id,reduces=mapred_reduce_tasks)
			saveJobResult(job_res,cluster_size,master_ip,mapred_reduce_tasks,job_number,output_file)
			if (job_res['status'] == 'SUCCEEDED'):
				numSucceededJobs += 1
		
			#deleteHDFSFolder(private_keypair_path,master_ip)
			print "Break time... go take a coffee and relax!"
			time.sleep(30)
		except Exception, e:
			print "Exception: ", e
			connection = getConnection(user, password, project_name, project_id, main_ip)
	
	#connection['sahara'].deleteCluster(cluster_id)
	
	print 'FINISHED FOR CLUSTER ' + cluster_name
#	sentMail()
