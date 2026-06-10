from ynet_daily import ynet_daily
from Reshet13_daily import Reshet13_daily
from now14_daily import now14_daily
from KanNews_daily import KanNews_daily
from Keshet12_daily import Keshet12_daily
from I24_daily import I24_daily

if __name__ == "__main__":

    try:
        Reshet13_daily()
        print("\nReshet13_daily - DONE")
    except Exception as e:
        print("\nReshet13_daily - ERROR")

    try:
        KanNews_daily()
        print("\nKanNews_daily - DONE")
    except Exception as e:
        print("\nKanNews_daily - ERROR")

    try:
        ynet_daily()
        print("\nynet_daily - DONE")
    except Exception as e:
        print("\nynet_daily - ERROR")

    try:
        now14_daily()
        print("\nnow14_daily_check - DONE")
    except Exception as e:
        print("\nnow14_daily_check - ERROR")

    try:
        I24_daily()
        print("\nI24_daily_check - DONE")
    except Exception as e:
        print("\nI24_daily_check - ERROR")

    try:
        Keshet12_daily()
        print("\nKeshet12_daily - DONE")
    except Exception as e:
        print("\nKeshet12_daily - ERROR")