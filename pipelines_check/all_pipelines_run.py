from Keshet12_check import Keshet12_daily_check
from Reshet13_check import Reshet13_daily_check
from KanNews_check import  KanNews_daily_check
from ynet_check import ynet_daily_check
from now14_check import now14_daily_check
from I24_check import I24_daily_check

if __name__ == "__main__":

    try:
        Reshet13_daily_check()
        print("Reshet13_daily - DONE")
    except Exception as e:
        print("Reshet13_daily - ERROR")

    try:
        KanNews_daily_check()
        print("KanNews_daily - DONE")
    except Exception as e:
        print("KanNews_daily - ERROR")

    try:
        ynet_daily_check()
        print("ynet_daily - DONE")
    except Exception as e:
        print("ynet_daily - ERROR")

    try:
        now14_daily_check()
        print("now14_daily_check - DONE")
    except Exception as e:
        print("now14_daily_check - ERROR")

    try:
        I24_daily_check()
        print("I24_daily_check - DONE")
    except Exception as e:
        print("I24_daily_check - ERROR")

    try:
        Keshet12_daily_check()
        print("Keshet12_daily - DONE")
    except Exception as e:
        print("Keshet12_daily - ERROR")
