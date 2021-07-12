# -*-coding:utf-8-*-

import rpy2.robjects as robjects
from Bio import SeqIO
import numpy as np
import pysam
import gc

from cbs import segment


def read_bam_file(filename):
    samfile = pysam.AlignmentFile(filename, "rb", ignore_truncation=True)
    chr_list = samfile.references
    return chr_list


def binning(ref, chr_len, bam_path, bin_size=1000):
    chr_tag = np.full(23, 0)
    chr_list = np.arange(23)
    chr_max_num = int(chr_len.max() / bin_size) + 1
    init_rd = np.full((23, chr_max_num), 0.0)
    # read bam file and get bin rd
    print("Read bam file: " + str(bam_path))
    samfile = pysam.AlignmentFile(bam_path, "rb", ignore_truncation=True)
    for line in samfile:
        idx = int(line.pos / bin_size)
        if line.reference_name == '21':
            init_rd[21][idx] += 1
            chr_tag[21] = 1
        # if line.reference_name:
        #     chr_name = line.reference_name.strip('chr')
        #     if chr_name.isdigit():
        #         init_rd[int(chr_name)][idx] += 1
        #         chr_tag[int(chr_name)] = 1

    chr_list = chr_list[chr_tag > 0]
    chr_num = len(chr_list)
    rd_list = [[] for _ in range(chr_num)]
    pos_list = [[] for _ in range(chr_num)]
    init_gc = np.full((chr_num, chr_max_num), 0)
    pos = np.full((chr_num, chr_max_num), 0)

    # initialize bin_data and bin_head
    count = 0
    for i in range(len(chr_list)):
        chr_id = chr_list[i]
        bin_num = int(chr_len[chr_id] / bin_size) + 1
        for j in range(bin_num):
            pos[i][j] = j
            cur_ref = ref[chr_id][j * bin_size:(j + 1) * bin_size]
            # print("cur_ref", type(cur_ref))
            N_count = cur_ref.count('N') + cur_ref.count('n')
            if N_count == 0:
                gc_count = cur_ref.count('C') + cur_ref.count('c') + cur_ref.count('G') + cur_ref.count('g')
            else:
                gc_count = 0
                init_rd[chr_id][j] = -1000000
                count = count + 1
            init_gc[i][j] = int(round(gc_count / bin_size, 3) * 1000)

        # delete
        cur_rd = init_rd[chr_id][: bin_num]
        cur_GC = init_gc[i][: bin_num]
        cur_pos = pos[i][: bin_num]
        cur_rd = cur_rd / 1000
        index = cur_rd >= 0
        rd = cur_rd[index]
        GC = cur_GC[index]
        cur_pos = cur_pos[index]
        # print("RD.shape", RD.shape)
        rd[rd == 0] = mode_rd(rd)
        rd = gc_correct(rd, GC)
        pos_list[i].append(cur_pos)
        rd_list[i].append(rd)
    del init_rd, init_gc, pos
    gc.collect()
    return rd_list, pos_list, chr_list


def mode_rd(rd):
    new_rd = np.round(rd, 3) * 1000
    new_rd = new_rd.astype(int)
    count = np.bincount(new_rd)

    if len(count) - 49 <= 0:
        count_list = np.full(len(count), 0)
    else:
        count_list = np.full(len(count) - 49, 0)
    for i in range(len(count_list)):
        count_list[i] = np.mean(count[i:i + 50])
    mode_min = np.argmax(count_list)
    mode_max = mode_min + 50
    mode = (mode_max + mode_min) / 2
    mode = mode / 1000
    return mode


def gc_correct(rd, GC):
    """
    correcting gc bias
    """
    bin_count = np.bincount(GC)
    global_rd_ave = np.mean(rd)
    for i in range(len(rd)):
        if bin_count[GC[i]] < 2:
            continue
        # mean = np.mean(RD[GC == GC[i]])
        mean = np.mean(rd[abs(GC - GC[i]) < 0.001])
        rd[i] = global_rd_ave * rd[i] / mean
    return rd


def read_seg_file(segpath, num_col, num_bin):
    """
    read segment file (Generated by DNAcopy.segment)
    seg file: col, chr, start, end, num_mark, seg_mean
    """
    seg_start = []
    seg_end = []
    seg_count = []
    seg_len = []
    with open(segpath, 'r') as f:
        for line in f:
            linestrlist = line.strip().split('\t')
            start = (int(linestrlist[0]) - 1) * num_col + int(linestrlist[2]) - 1
            end = (int(linestrlist[0]) - 1) * num_col + int(linestrlist[3]) - 1
            if start == end:
                seg_end[-1] += 1
                continue
            if start < num_bin:
                if end > num_bin:
                    end = num_bin - 1
                seg_start.append(start)
                seg_end.append(end)
                seg_count.append(float(linestrlist[5]))
                seg_len.append(int(linestrlist[4]))
    seg_start = np.array(seg_start)
    seg_end = np.array(seg_end)

    return seg_start, seg_end, seg_count, seg_len


def segmentation_cbs_r(seg_path, rd, pos, bin_size, bin_num, ncol=50):

    def _get_rd_values(rd, pos, seg_start, seg_end, bin_size):
        per_seg_rd = []
        for i in range(len(seg_end)):
            seg = rd[seg_start[i]: seg_end[i]]
            per_seg_rd.append([np.mean(seg)])
            seg_start[i] = pos[seg_start[i]] * bin_size + 1
            if seg_end[i] == len(pos):
                seg_end[i] = len(pos) - 1
            seg_end[i] = pos[seg_end[i]] * bin_size + bin_size

        return per_seg_rd, seg_start, seg_end

    v = robjects.FloatVector(rd)
    m = robjects.r['matrix'](v, ncol=ncol)
    robjects.r.source("CBS_data.R")
    robjects.r.CBS_data(m, seg_path)

    num_col = int(bin_num / ncol) + 1
    seg_start, seg_end, seg_count, seg_len = read_seg_file(seg_path, num_col, bin_num)

    seg_start = seg_start[:-1]
    seg_end = seg_end[:-1]

    return _get_rd_values(rd, pos, seg_start, seg_end, bin_size)


def segmentation_cbs_py(rd, pos, bin_size):

    def _get_rd_values(rd, pos, seg_index, bin_size):
        seg_rd = []
        seg_start = np.full(len(seg_index), 0)
        seg_end = np.full(len(seg_index), 0)
        for i in range(len(seg_index)):
            segment = rd[seg_index[i][0]: seg_index[i][1]]
            seg_rd.append([np.mean(segment)])
            seg_start[i] = pos[seg_index[i][0]] * bin_size + 1
            if seg_end[i] == len(pos):
                seg_end[i] = len(pos) - 1
            seg_end[i] = pos[seg_index[i][1] - 1] * bin_size + bin_size

        return seg_rd, seg_start, seg_end

    seg_index = segment(rd)
    return _get_rd_values(rd, pos, seg_index, bin_size)


def preprocessing(bam_path, fa_path, bin_size=1000, ncol=50, cbs_imp='python'):
    """
    Process the bam file and generate the RD profile

    Parameters
    ----------
    bam_path : str
        local path of the *.bam file

    fa_path : str
        local path of the *.fasta file

    bin_size : int, optional (default=1000)
        the bin size.

    cbs_imp: str, optional (default='python')
        The implementation of CBS algorithm. In addition to "python", cbs_imp can also be "R".

    ncol : int, optional (default=50)
        the number of  partitions to CBS in R.

    Returns
    ----------

    """

    # ref_path = "/home/mk422/Documents/Code/Python/genetic_analysis/reference"
    # seg_path = ref_path + "/seg"
    seg_path = "data/seg"

    ref = [[] for _ in range(23)]
    ref_list = read_bam_file(bam_path)
    for i in range(len(ref_list)):
        chr_id = ref_list[i]
        if chr_id == '21':
            fa_seq = SeqIO.read(fa_path, "fasta")
            ref[21] = str(fa_seq.seq)

    chr_len = np.full(23, 0)
    for i in range(1, 23):
        chr_len[i] = len(ref[i])
    rd_list, pos_list, chr_list = binning(ref, chr_len, bam_path, bin_size)
    all_chr = []
    all_rd = []
    all_start = []
    all_end = []
    mode_list = np.full(len(chr_list), 0.0)
    for i in range(len(chr_list)):

        rd = np.array(rd_list[i][0])
        pos = np.array(pos_list[i][0])
        bin_num = len(rd)
        mode_list[i] = mode_rd(rd)  # average RD values for all bins

        print("segment count...")
        if cbs_imp.lower() == 'python':
            seg_rd, seg_start, seg_end = segmentation_cbs_py(rd, pos, bin_size)

        else:
            seg_rd, seg_start, seg_end = segmentation_cbs_r(seg_path, rd, pos, bin_size, bin_num, ncol)
        all_rd.extend(seg_rd)
        all_start.extend(seg_start)
        all_end.extend(seg_end)
        all_chr.extend(chr_list[i] for _ in range(len(seg_rd)))

    all_chr = np.array(all_chr)
    all_start = np.array(all_start)
    all_end = np.array(all_end)
    all_rd = np.array(all_rd)
    for i in range(len(all_rd)):
        if np.isnan(all_rd[i, :]).any():
            all_rd[i, :] = (all_rd[i - 1, :] + all_rd[i + 1, :]) / 2

    return [all_chr, all_start, all_end, all_rd, np.mean(mode_list)]

