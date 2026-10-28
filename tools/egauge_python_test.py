#import the egauge api
from egauge import webapi


"""
This sets up the login info, the URI is the uri to the egauge we are connecting to, the username
and password are the login credentials you were given to log into the eguage website
"""
# NOTE: change the username and password to your username and password provided
URI = "https://egauge18646.egaug.es" # meter name is egauge18646
USR = "user" # user is your username
PWD = "password" # password is your password

#get the device from teh webapi
dev = webapi.device.Device(URI, webapi.JWTAuth(USR,PWD))

#simple print functions getting the host name and some register data
print("hostname is " + dev.get("/config/net/hostname")["result"])

#it is not clear to me what the register data returned is at the moment becuase data sharing is not on, 
#however there is data returned here
print(dev.get('/register?reg=3+5+7+9&rate'))
