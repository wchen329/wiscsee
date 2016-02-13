import simpy
import FtlSim
from collections import Counter
from commons import *

class FlashAddress(object):
    def __init__(self):
        self.page_index = 5
        self.block_index = 4
        self.plane_index = 3
        self.chip_index = 2
        self.package_index = 1
        self.channel_index = 0

        self.names = ['channel', 'package', 'chip', 'plane', 'block', 'page']
        self.location = [0 for _ in self.names]

    def __str__(self):
        lines = []
        for name, no in zip(self.names, self.location):
            lines.append(name.ljust(8) + str(no))
        return '\n'.join(lines)

    @property
    def page(self):
        return self.location[self.page_index]
    @page.setter
    def page(self, value):
        self.location[self.page_index] = value

    @property
    def block(self):
        return self.location[self.block_index]
    @block.setter
    def block(self, value):
        self.location[self.block_index] = value

    @property
    def plane(self):
        return self.location[self.plane_index]
    @plane.setter
    def plane(self, value):
        self.location[self.plane_index] = value

    @property
    def chip(self):
        return self.location[self.chip_index]
    @chip.setter
    def chip(self, value):
        self.location[self.chip_index] = value

    @property
    def package(self):
        return self.location[self.package_index]
    @package.setter
    def package(self, value):
        self.location[self.package_index] = value

    @property
    def channel(self):
        return self.location[self.channel_index]
    @channel.setter
    def channel(self, value):
        self.location[self.channel_index] = value


class FlashRequest(object):
    # OP_READ, OP_WRITE, OP_ERASE = 'OP_READ', 'OP_WRITE', 'OP_ERASE'
    def __init__(self):
        self.addr = None
        self.operation = None

    def __str__(self):
        lines = []
        lines.append( "OPERATION " + str(self.operation) )
        lines.append( str(self.addr) )
        return '\n'.join(lines)

class FlatFlashPageRequest(object):
    def __init__(self, page_start, page_count, op):
        """
        op is one of OP_READ, OP_WRITE
        """
        assert op != OP_ERASE
        self.page_start = page_start
        self.page_count = page_count
        self.op = op

    def get_range(self):
        return self.page_start, self, page_count

class FlatFlashBlockRequest(object):
    def __init__(self, block_start, block_count, op):
        """
        op is one of OP_ERASE
        """
        assert op == OP_ERASE
        self.block_start = block_start
        self.block_count = block_count
        self.op = op

    def get_range(self):
        return self.block_start, self, block_count


def display_flash_requests(requests):
    reqs = [str(req) for req in requests]
    print '\n'.join(reqs)


def create_flashrequest(addr, op):
    req = FlashRequest()
    req.addr = addr

    if op == 'read':
        req.operation = OP_READ
    elif op == 'write':
        req.operation = OP_WRITE
    elif op == 'erase':
        req.operation = OP_ERASE
    else:
        raise RuntimeError()

    return req


class Controller(object):
    def __init__(self, simpy_env, conf):
        self.env = simpy_env
        self.conf = conf

        self.page_size = self.conf['flash_config']['page_size']
        self.n_pages_per_block = self.conf['flash_config']['n_pages_per_block']
        self.n_blocks_per_plane = self.conf['flash_config']['n_blocks_per_plane']
        self.n_planes_per_chip = self.conf['flash_config']['n_planes_per_chip']
        self.n_chips_per_package = self.conf['flash_config']['n_chips_per_package']
        self.n_packages_per_channel = self.conf['flash_config']['n_packages_per_channel']
        self.n_channels_per_dev = self.conf['flash_config']['n_channels_per_dev']

        self.n_pages_per_plane = self.n_pages_per_block * self.n_blocks_per_plane
        self.n_pages_per_chip = self.n_pages_per_plane * self.n_planes_per_chip
        self.n_pages_per_package = self.n_pages_per_chip * self.n_chips_per_package
        self.n_pages_per_channel = self.n_pages_per_package * self.n_packages_per_channel
        self.n_pages_per_dev = self.n_pages_per_channel * self.n_channels_per_dev

        self.page_hierarchy = [self.n_pages_per_channel,
                                self.n_pages_per_package,
                                self.n_pages_per_chip,
                                self.n_pages_per_plane,
                                self.n_pages_per_block]

        self.channels = [Channel(self.env, conf, i)
                for i in range( self.n_channels_per_dev)]

    def get_flash_requests_for_pbns(self, block_start, block_count, op):
        ret_requests = []
        for block in range(block_start, block_start + block_count):
            machine_block_addr = self.physical_to_machine_block(block)
            flash_req = create_flashrequest( machine_block_addr, op = op)
            ret_requests.append(flash_req)

        return ret_requests

    def get_flash_requests_for_ppns(self, page_start, page_count, op):
        """
        op can be 'read', 'write', and 'erase'
        """
        ret_requests = []
        for page in range(page_start, page_start + page_count):
            machine_page_addr = self.physical_to_machine_page(page)
            flash_req = create_flashrequest(machine_page_addr, op = op)
            ret_requests.append(flash_req)

        return ret_requests

    def physical_to_machine_page(self, page):
        addr = FlashAddress()

        no = page
        # page_hierarchy has [channel, package, ..., block]
        # location has       [channel, package, ..., block, page]
        for i, count in enumerate(self.page_hierarchy):
            addr.location[i] = no / count
            no = no % count
        addr.location[-1] = no

        return addr

    def physical_to_machine_block(self, block):
        """
        We first translate block to the page number of its first page,
        so we can use the existing physical_to_machine_page
        """
        page = block * self.n_pages_per_block

        addr = self.physical_to_machine_page(page)
        addr.page = None # so we dont' mistakely use it for other purposes

        return addr

    def rw_ppn_extent(self, ppn_start, ppn_count, op):
        """
        op is 'read' or 'write'
        """
        flash_reqs = self.get_flash_requests_for_ppns(ppn_start, ppn_count,
            op = op)
        yield self.env.process( self.execute_request_list(flash_reqs) )

    def erase_pbn_extent(self, pbn_start, pbn_count):
        flash_reqs = self.get_flash_requests_for_pbns(pbn_start, pbn_count,
                op = 'erase')
        yield self.env.process( self.execute_request_list(flash_reqs) )

    def write_page(self, addr, data = None):
        """
        Usage:
            if you do:
            yield env.process(controller.write_page(addr))
            the calling process will wait until write_page() finishes

            if you do
            controller.write_page(addr)
            the calling process will not wait

            if you do
            controller.write_page(addr)
            controller.write_page(addr) # to same channel
            the calling process will not wait
            the second write has to wait for the first
        """
        yield self.env.process(
            self.channels[addr.channel].write_page(None))

    def read_page(self, addr):
        yield self.env.process(
            self.channels[addr.channel].read_page(None))

    def erase_block(self, addr):
        yield self.env.process(
            self.channels[addr.channel].erase_block(None))

    def execute_request(self, flash_request):
        if flash_request.operation == OP_READ:
            yield self.env.process(
                    self.read_page(flash_request.addr))
        elif flash_request.operation == OP_WRITE:
            yield self.env.process(
                self.write_page(flash_request.addr))
        elif flash_request.operation == OP_ERASE:
            yield self.env.process(
                self.erase_block(flash_request.addr))
        else:
            raise RuntimeError("operation {} is not supported".format(
                flash_request.operation))

    def execute_request_list(self, flash_request_list):
        procs = []
        for request in flash_request_list:
            p = self.env.process(self.execute_request(request))
            procs.append(p)
        event = simpy.events.AllOf(self.env, procs)
        yield event


class Controller2(Controller):
    """
    This controller has a recorder
    """
    def __init__(self, simpy_env, conf, recorderobj):
        super(Controller2, self).__init__(simpy_env, conf)
        self.recorder = recorderobj
        self.flash_backend = FtlSim.flash.SimpleFlash(recorderobj, conf)

    def get_max_channel_page_count(self, ppns):
        """
        Find the max count of the channels
        """
        pbns = []
        for ppn in ppns:
            if ppn == 'UNINIT':
                # skip it so unitialized ppn does not involve flash op
                continue
            block, _ = self.conf.page_to_block_off(ppn)
            pbns.append(block)

        return self.get_max_channel_block_count(pbns)

    def get_max_channel_block_count(self, pbns):
        channel_counter = Counter()
        for pbn in pbns:
            channel, _ = FtlSim.dftldes.block_to_channel_block(self.conf, pbn)
            channel_counter[channel] += 1

        return self.find_max_count(channel_counter)

    def find_max_count(self, channel_counter):
        if len(channel_counter) == 0:
            return 0
        else:
            max_channel, max_count = channel_counter.most_common(1)[0]
            return max_count

    def read_pages(self, ppns, tag):
        """
        Read ppns in batch and calculate time
        lpns are the corresponding lpns of ppns, we pass them in for checking
        """
        max_count = self.get_max_channel_page_count(ppns)

        data = []
        for ppn in ppns:
            data.append( self.flash_backend.page_read(ppn, tag) )
        return data

    def write_pages(self, ppns, ppn_data, tag):
        """
        This function will store ppn_data to flash and calculate the time
        it takes to do it with real flash.

        The access time is determined by the channel with the longest request
        queue.
        """
        max_count = self.get_max_channel_page_count(ppns)

        # save the data to flash
        if ppn_data == None:
            for ppn in ppns:
                self.flash_backend.page_write(ppn, tag)
        else:
            for ppn, item in zip(ppns, ppn_data):
                self.flash_backend.page_write(ppn, tag, data = item)

    def erase_blocks(self, pbns, tag):
        max_count = self.get_max_channel_block_count(pbns)

        for block in pbns:
            self.flash_backend.block_erase(block, cat = tag)


class Channel(object):
    """
    This is a channel with only single package, chip, and plane. This is how a
    request is processed in it:

    This is a channel without pipelining. It is simply a resource that cannot
    be shared. It simply adds delay to the operation.

    Read:
        7*t_wc + t_R + nbytes*t_rc
    write:
        7*t_wc + nbytes*t_wc + t_prog
    """
    def __init__(self, simpy_env, conf, channel_id = None):
        self.env = simpy_env
        self.conf = conf
        self.resource = simpy.Resource(self.env, capacity = 1)
        self.channel_id = channel_id

        t_wc = 1
        t_r = 1
        t_rc = 1
        t_prog = 1
        t_erase = 1
        page_size = self.conf['flash_config']['page_size']

        # self.read_time = 7 * t_wc + t_r + page_size * t_rc
        # self.program_time = 7 * t_wc + page_size * t_wc + t_prog
        # self.erase_time = 5 * t_wc + t_erase

        self.read_time = 1
        self.program_time = 2
        self.erase_time = 3

    def write_page(self, addr = None , data = None):
        """
        If you want to when this operation is finished, just print env.now.
        If you want to know how long it takes, use env.now before and after
        the operation.
        """
        with self.resource.request() as request:
            yield request
            yield self.env.timeout( self.program_time )

    def read_page(self, addr = None):
        with self.resource.request() as request:
            yield request
            yield self.env.timeout( self.read_time )

    def erase_block(self, addr = None):
        with self.resource.request() as request:
            yield request
            yield self.env.timeout( self.erase_time )



