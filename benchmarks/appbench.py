import csv
import collections
import os
import glob
import time

from utilities import utils
from experimenter import *
from expconfs import ParameterPool
import filesim

from pyreuse.sysutils.straceParser import parse_and_write_dirty_table


def run_on_real_dev(para):
    Parameters = collections.namedtuple("Parameters", ','.join(para.keys()))
    obj = RealDevExperimenter( Parameters(**para) )
    obj.main()


def execute_simulation(para):
    """
    INPUT: para is a dictionary generated by filesim.ParaDict

    This function is only for simulating blktrace events as LBA workload
    """
    default_para = get_shared_nolist_para_dict(None, None)
    default_para.update(para)
    para = default_para
    Parameters = collections.namedtuple("Parameters", ','.join(para.keys()))
    obj = filesim.LocalExperimenter( Parameters(**para) )
    obj.main()


