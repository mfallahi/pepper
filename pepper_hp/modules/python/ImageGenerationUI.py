import time
import os
import sys
import concurrent.futures
from datetime import datetime

from pepper_hp.modules.python.DataStore import DataStore
from pepper_hp.modules.python.AlignmentSummarizer import AlignmentSummarizer
from pepper_hp.modules.python.Options import ImageSizeOptions

from pepper_hp.build import PEPPER_HP


class UserInterfaceView:
    """
    Process manager that runs sequence of processes to generate images and their labels.
    """
    def __init__(self, chromosome_name, bam_file_path, draft_file_path, truth_bam, train_mode):
        """
        Initialize a manager object
        :param chromosome_name: Name of the chromosome
        :param bam_file_path: Path to the BAM file
        :param draft_file_path: Path to the reference FASTA file
        :param truth_bam: Path to the truth sequence to reference mapping file
        """
        # --- initialize handlers ---
        # create objects to handle different files and query
        self.bam_path = bam_file_path
        self.fasta_path = draft_file_path
        self.bam_handler = PEPPER_HP.BAM_handler(bam_file_path)
        self.fasta_handler = PEPPER_HP.FASTA_handler(draft_file_path)
        self.train_mode = train_mode
        self.downsample_rate = 1.0
        self.truth_bam = None

        if self.train_mode:
            self.truth_bam = truth_bam

        # --- initialize names ---
        # name of the chromosome
        self.chromosome_name = chromosome_name

    def parse_region(self, start_position, end_position, realignment_flag):
        """
        Generate labeled images of a given region of the genome
        :param start_position: Start position of the region
        :param end_position: End position of the region
        :param realignment_flag: If true then realignment will be performed
        :return:
        """
        alignment_summarizer = AlignmentSummarizer(self.bam_handler,
                                                   self.fasta_handler,
                                                   self.chromosome_name,
                                                   start_position,
                                                   end_position)

        images_hp1, labels_hp1, positions_hp1, image_chunk_ids_hp1, all_ref_seq_hp1, \
        images_hp2, labels_hp2, positions_hp2, image_chunk_ids_hp2, all_ref_seq_hp2 = \
            alignment_summarizer.create_summary(self.truth_bam,
                                                self.train_mode,
                                                realignment_flag)

        return images_hp1, labels_hp1, positions_hp1, image_chunk_ids_hp1, all_ref_seq_hp1, \
               images_hp2, labels_hp2, positions_hp2, image_chunk_ids_hp2, all_ref_seq_hp2


class UserInterfaceSupport:
    """
    THIS CLASS HOLDS STATIC METHODS THAT HELP AS USER INTERFACE FOR IMAGE GENERATION
    """
    @staticmethod
    def handle_output_directory(output_directory):
        """
        Process the output directory and return a valid directory where we save the output
        :param output_directory: Output directory path
        :return:
        """
        # process the output directory
        if output_directory[-1] != "/":
            output_directory += "/"
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)

        return output_directory

    @staticmethod
    def get_chromosome_list(chromosome_names, ref_file, region_bed):
        """
        PARSES THROUGH THE CHROMOSOME PARAMETER TO FIND OUT WHICH REGIONS TO PROCESS
        :param chromosome_names: NAME OF CHROMOSOME
        :param ref_file: PATH TO THE REFERENCE FILE
        :return: LIST OF CHROMOSOME IN REGION SPECIFIC FORMAT
        """
        if not chromosome_names:
            fasta_handler = PEPPER_HP.FASTA_handler(ref_file)
            chromosome_names = fasta_handler.get_chromosome_names()
            chromosome_names = ','.join(chromosome_names)

        if region_bed:
            chromosome_name_list = []
            with open(region_bed) as fp:
                line = fp.readline()
                cnt = 1
                while line:
                    line_to_list = line.rstrip().split('\t')
                    chr_name, start_pos, end_pos = line_to_list[0], int(line_to_list[1]), int(line_to_list[2])
                    region = sorted([start_pos, end_pos])
                    chromosome_name_list.append((chr_name, region))
                    line = fp.readline()
                cnt += 1
            return chromosome_name_list

        split_names = chromosome_names.strip().split(',')
        split_names = [name.strip() for name in split_names]

        chromosome_name_list = []
        for name in split_names:
            # split on region
            region = None
            if ':' in name:
                name_region = name.strip().split(':')

                if len(name_region) != 2:
                    sys.stderr.write("ERROR: --region INVALID value.\n")
                    exit(0)

                name, region = tuple(name_region)
                region = region.strip().split('-')
                region = [int(pos) for pos in region]

                if len(region) != 2 or not region[0] <= region[1]:
                    sys.stderr.write("ERROR: --region INVALID value.\n")
                    exit(0)

            range_split = name.split('-')
            if len(range_split) > 1:
                chr_prefix = ''
                for p in name:
                    if p.isdigit():
                        break
                    else:
                        chr_prefix = chr_prefix + p

                int_ranges = []
                for item in range_split:
                    s = ''.join(i for i in item if i.isdigit())
                    int_ranges.append(int(s))
                int_ranges = sorted(int_ranges)

                for chr_seq in range(int_ranges[0], int_ranges[-1] + 1):
                    chromosome_name_list.append((chr_prefix + str(chr_seq), region))
            else:
                chromosome_name_list.append((name, region))

        return chromosome_name_list

    @staticmethod
    def single_worker(args, _start, _end):
        chr_name, bam_file, draft_file, truth_bam, train_mode, realignment_flag = args

        view = UserInterfaceView(chromosome_name=chr_name,
                                 bam_file_path=bam_file,
                                 draft_file_path=draft_file,
                                 truth_bam=truth_bam,
                                 train_mode=train_mode)

        images_hp1, labels_hp1, positions_hp1, image_chunk_ids_hp1, ref_seq_hp1, \
        images_hp2, labels_hp2, positions_hp2, image_chunk_ids_hp2, ref_seq_hp2 = view.parse_region(_start, _end, realignment_flag)
        region = (chr_name, _start, _end)

        return images_hp1, labels_hp1, positions_hp1, image_chunk_ids_hp1, region, ref_seq_hp1, \
               images_hp2, labels_hp2, positions_hp2, image_chunk_ids_hp2, region, ref_seq_hp2

    @staticmethod
    def image_generator(args, all_intervals, total_threads, thread_id):
        thread_prefix = "[THREAD " + "{:02d}".format(thread_id) + "]"

        output_path, bam_file, draft_file, truth_bam, train_mode, realignment_flag = args
        file_name_hp1 = output_path + "hp1_images/pepper_hp_images_thread_" + str(thread_id) + "_hp1.hdf"
        file_name_hp2 = output_path + "hp2_images/pepper_hp_images_thread_" + str(thread_id) + "_hp2.hdf"

        intervals = [r for i, r in enumerate(all_intervals) if i % total_threads == thread_id]

        # initial notification
        if thread_id == 0:
            sys.stderr.write("[" + datetime.now().strftime('%m-%d-%Y %H:%M:%S') + "] "
                             + "STARTING THREAD: " + str(thread_id)
                             + " FOR " + str(len(intervals)) + " INTERVALS\n")
        sys.stderr.flush()
        start_time = time.time()
        with DataStore(file_name_hp1, 'w') as output_hdf_file_hp1, DataStore(file_name_hp2, 'w') as output_hdf_file_hp2:
            for counter, interval in enumerate(intervals):
                chr_name, _start, _end = interval
                img_args = (chr_name, bam_file, draft_file, truth_bam, train_mode, realignment_flag)
                images_hp1, labels_hp1, positions_hp1, chunk_ids_hp1, region_hp1, ref_seqs_hp1, \
                images_hp2, labels_hp2, positions_hp2, chunk_ids_hp2, region_hp2, ref_seqs_hp2 = \
                    UserInterfaceSupport.single_worker(img_args, _start, _end)

                for i, image in enumerate(images_hp1):
                    label = labels_hp1[i]
                    position, index = zip(*positions_hp1[i])
                    ref_seq = ref_seqs_hp1[i]
                    chunk_id = chunk_ids_hp1[i]
                    summary_name = str(region_hp1[0]) + "_" + str(region_hp1[1]) + "_" + str(region_hp1[2]) + "_" + str(chunk_id)

                    output_hdf_file_hp1.write_summary(region_hp1, image, label, position, index, chunk_id, summary_name, ref_seq)

                for i, image in enumerate(images_hp2):
                    label = labels_hp2[i]
                    position, index = zip(*positions_hp2[i])
                    ref_seq = ref_seqs_hp2[i]
                    chunk_id = chunk_ids_hp2[i]
                    summary_name = str(region_hp2[0]) + "_" + str(region_hp2[1]) + "_" + str(region_hp2[2]) + "_" + str(chunk_id)

                    output_hdf_file_hp2.write_summary(region_hp2, image, label, position, index, chunk_id, summary_name, ref_seq)

                if counter > 0 and counter % 10 == 0:
                    percent_complete = int((100 * counter) / len(intervals))
                    time_now = time.time()
                    mins = int((time_now - start_time) / 60)
                    secs = int((time_now - start_time)) % 60
                    if thread_id == 0:
                        sys.stderr.write("[" + datetime.now().strftime('%m-%d-%Y %H:%M:%S') + "]"
                                         + " INFO: " + thread_prefix + " " + str(counter) + "/" + str(len(intervals))
                                         + " COMPLETE (" + str(percent_complete) + "%)"
                                         + " [ELAPSED TIME: " + str(mins) + " Min " + str(secs) + " Sec]\n")

        return thread_id

    @staticmethod
    def chromosome_level_parallelization(chr_list,
                                         bam_file,
                                         draft_file,
                                         truth_bam,
                                         output_path,
                                         total_threads,
                                         train_mode,
                                         realignment_flag):
        max_size = 10000
        start_time = time.time()
        fasta_handler = PEPPER_HP.FASTA_handler(draft_file)

        all_intervals = []
        # first calculate all the intervals that we need to process
        for chr_name, region in chr_list:
            # contig update message
            if not region:
                interval_start, interval_end = (0, fasta_handler.get_chromosome_sequence_length(chr_name) - 1)
            else:
                interval_start, interval_end = tuple(region)
                interval_start = max(0, interval_start)
                interval_end = min(interval_end, fasta_handler.get_chromosome_sequence_length(chr_name) - 1)

            # this is the interval size each of the process is going to get which is 10^6
            # I will split this into 10^4 size inside the worker process
            for pos in range(interval_start, interval_end, max_size):
                pos_start = max(interval_start, pos - ImageSizeOptions.MIN_IMAGE_OVERLAP)
                pos_end = min(interval_end, pos + max_size + ImageSizeOptions.MIN_IMAGE_OVERLAP)
                all_intervals.append((chr_name, pos_start, pos_end))

        # all intervals calculated now
        # contig update message
        sys.stderr.write("[" + datetime.now().strftime('%m-%d-%Y %H:%M:%S') + "] "
                         + "INFO: TOTAL CONTIGS: " + str(len(chr_list))
                         + " TOTAL INTERVALS: " + str(len(all_intervals)) + "\n")
        sys.stderr.flush()

        args = (output_path, bam_file, draft_file, truth_bam, train_mode, realignment_flag)
        with concurrent.futures.ProcessPoolExecutor(max_workers=total_threads) as executor:
            futures = [executor.submit(UserInterfaceSupport.image_generator, args, all_intervals, total_threads, thread_id)
                       for thread_id in range(0, total_threads)]

            for fut in concurrent.futures.as_completed(futures):
                if fut.exception() is None:
                    # get the results
                    thread_id = fut.result()
                    if thread_id == 0:
                        sys.stderr.write("[" + datetime.now().strftime('%m-%d-%Y %H:%M:%S') + "] "
                                             + "THREAD " + str(thread_id) + " FINISHED SUCCESSFULLY.\n")
                else:
                    sys.stderr.write("ERROR: " + str(fut.exception()) + "\n")
                fut._result = None  # python issue 27144

        end_time = time.time()
        mins = int((end_time - start_time) / 60)
        secs = int((end_time - start_time)) % 60
        sys.stderr.write("[" + datetime.now().strftime('%m-%d-%Y %H:%M:%S') + "] INFO: FINISHED IMAGE GENERATION\n")
        sys.stderr.write("[" + datetime.now().strftime('%m-%d-%Y %H:%M:%S') + "] INFO: ELAPSED TIME: " + str(mins) + " Min " + str(secs) + " Sec\n")
