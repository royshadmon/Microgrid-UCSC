import psycopg2
from dotenv import load_dotenv
import os
from supabase import create_client, Client

# Load environment variables from .env
load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)


def supabase_signup(email, password, firstname, lastname):
    response = supabase.auth.sign_up(
        {
            "email": email,
            "password": password,
            "options": {"data": {"first_name": firstname, "last_name": lastname}},
        }
    )

    return response


def supabase_login(email, password):
    try:
        response = supabase.auth.sign_in_with_password(
            {
                "email": email,
                "password": password,
            }
        )
        return response
    except Exception as e:
        print("Error logging in:", e)
        return e


def supabase_logout():
    response = supabase.auth.sign_out()
    return response


def supabase_get_user(jwt):
    user = supabase.auth.get_user(jwt)
    # print("User", user)
    return user


def supabase_refresh_session():
    session = supabase.auth.refresh_session()
    print("session", session)
    return session


def supabase_bookmark_node(id, node):
    existing = (
        supabase.table("bookmarks")
        .select("id")
        .eq("user_id", id)
        .eq("node", node)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing  # or return a custom “already bookmarked” message

    # 2) Otherwise insert
    response = (
        supabase.table("bookmarks").insert({"user_id": id, "node": node}).execute()
    )
    return response


def supabase_get_bookmarked_nodes(id):
    response = supabase.table("bookmarks").select("*").eq("user_id", id).execute()
    return response


def supabase_delete_bookmarked_node(id, node):
    response = (
        supabase.table("bookmarks")
        .delete()
        .eq("user_id", id)
        .eq("node", node)
        .execute()
    )
    return response


def supabase_update_bookmark_description(id, node, description):
    response = (
        supabase.table("bookmarks")
        .update({"description": description})
        .eq("user_id", id)
        .eq("node", node)
        .execute()
    )
    return response


def supabase_add_preset_group(id, group_name):
    existing = (
        supabase.table("preset_groups")
        .select("id")
        .eq("user_id", id)
        .eq("group_name", group_name)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing  # or return a custom “already bookmarked” message

    # 2) Otherwise insert
    response = (
        supabase.table("preset_groups")
        .insert({"user_id": id, "group_name": group_name})
        .execute()
    )
    return response


def supabase_get_preset_groups(id):
    response = supabase.table("preset_groups").select("*").eq("user_id", id).execute()
    return response


def supabase_add_preset_to_group(id, group_id, command, type, button):
    # existing = (
    #   supabase
    #     .table("preset_commands")
    #     .select("id")
    #     .eq("user_id", id)
    #     .eq("group_name", group_name)
    #     .limit(1)
    #     .execute()
    # )
    # if existing.data:
    #     return existing  # or return a custom “already bookmarked” message

    # 2) Otherwise insert
    response = (
        supabase.table("preset_commands")
        .insert(
            {
                "user_id": id,
                "group_id": group_id,
                "command": command,
                "type": type,
                "button": button,
            }
        )
        .execute()
    )
    return response


def supabase_get_presets_by_group(id, group_id):
    response = (
        supabase.table("preset_commands")
        .select("*")
        .eq("user_id", id)
        .eq("group_id", group_id)
        .execute()
    )
    return response


def supabase_delete_preset_group(id, group_id):
    response = (
        supabase.table("preset_groups")
        .delete()
        .eq("user_id", id)
        .eq("id", group_id)
        .execute()
    )
    return response

# resp = supabase_signup("ppurathe@ucsc.edu", "pass1234", "peter", "pp")

# print(resp.user.id)


# clear local storage by going to the browser , inspect, application, storage, clear site data
