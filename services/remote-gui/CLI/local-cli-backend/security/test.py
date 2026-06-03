# # app/routers/users.py
# # from fastapi import APIRouter

# # router = APIRouter(
# #     prefix="/users",
# #     tags=["users"],
# #     responses={404: {"description": "User not found"}},
# # )

# # @router.get("/")
# # async def read_users():
# #     return [{"username": "Alice"}, {"username": "Bob"}]

# # @router.get("/{user_id}")
# # async def read_user(user_id: int):
# #     return {"username": f"User {user_id}"}

# # # main.py
# from fastapi import FastAPI
# from fastapi.middleware.cors import CORSMiddleware
# # from app.routers import users

# app = FastAPI()

# # app.include_router(users.router)



# <blockchain delete policy where id = a29bcfd55cef20c6834f29fbb3aaf882 and master = 172.24.0.2:32048>





# Security Notes:

# id generate certificate authority where country = US and state = CA and locality = "Redwood City" and org = AnyLog and hostname =  anylog.co
# id generate certificate request where country = US and state = CA and locality = "Redwood City" and org = "Acme Inc" and alt_names = 127.0.0.1 and hostname =  acme.co and ip = "192.56.76.4"

# id sign certificate request where ca_org = AnyLog and server_org = "Acme Inc"

# run rest server where external_ip=!ip and external_port=!rest_port and timeout = 0 and threads = 6 and ssl = true and ca_org = AnyLog and server_org = "Acme Inc"



# 192.168.86.21:32049