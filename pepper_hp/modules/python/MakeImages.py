import os
from pepper_hp.modules.python.ImageGenerationUI import UserInterfaceSupport


def make_images(bam, fasta, region, output_dir, hp_tag, threads):
    chr_list = UserInterfaceSupport.get_chromosome_list(region, fasta, region_bed=None)
    output_dir = UserInterfaceSupport.handle_output_directory(os.path.abspath(output_dir))

    UserInterfaceSupport.chromosome_level_parallelization(chr_list,
                                                          bam,
                                                          fasta,
                                                          truth_bam=None,
                                                          hp_tag=hp_tag,
                                                          output_path=output_dir,
                                                          total_threads=threads,
                                                          train_mode=False,
                                                          realignment_flag=False)
