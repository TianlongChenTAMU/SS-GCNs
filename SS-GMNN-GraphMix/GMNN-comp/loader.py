import sys
import os
import math
import numpy as np
import torch
from torch.autograd import Variable
import metis

class Vocab(object):

    def __init__(self, file_name, cols, with_padding=False):
        self.itos = []
        self.stoi = {}
        self.vocab_size = 0

        if with_padding:
            string = '<pad>'
            self.stoi[string] = self.vocab_size
            self.itos.append(string)
            self.vocab_size += 1

        fi = open(file_name, 'r')
        for line in fi:
            items = line.strip().split('\t')
            for col in cols:
                item = items[col]
                strings = item.strip().split(' ')
                for string in strings:
                    string = string.split(':')[0]
                    if string not in self.stoi:
                        self.stoi[string] = self.vocab_size
                        self.itos.append(string)
                        self.vocab_size += 1
        fi.close()

    def __len__(self):
        return self.vocab_size

class EntityLabel(object):

    def __init__(self, file_name, entity, label):
        self.vocab_n, self.col_n = entity
        self.vocab_l, self.col_l = label
        self.itol = [-1 for k in range(self.vocab_n.vocab_size)]

        fi = open(file_name, 'r')
        for line in fi:
            items = line.strip().split('\t')
            sn, sl = items[self.col_n], items[self.col_l]
            n = self.vocab_n.stoi.get(sn, -1)
            l = self.vocab_l.stoi.get(sl, -1)
            if n == -1:
                continue
            self.itol[n] = l
        fi.close()

class EntityFeature(object):

    def __init__(self, file_name, entity, feature):
        self.vocab_n, self.col_n = entity
        self.vocab_f, self.col_f = feature
        self.itof = [[] for k in range(len(self.vocab_n))]
        self.one_hot = []

        fi = open(file_name, 'r')
        for line in fi:
            items = line.strip().split('\t')
            sn, sf = items[self.col_n], items[self.col_f]
            n = self.vocab_n.stoi.get(sn, -1)
            if n == -1:
                continue
            for s in sf.strip().split(' '):
                f = self.vocab_f.stoi.get(s.split(':')[0], -1)
                w = float(s.split(':')[1])
                if f == -1:
                    continue
                self.itof[n].append((f, w))
        fi.close()

    def to_one_hot(self, binary=False):
        self.one_hot = [[0 for j in range(len(self.vocab_f))] for i in range(len(self.vocab_n))]
        for k in range(len(self.vocab_n)):
            sm = 0
            for fid, wt in self.itof[k]:
                if binary:
                    wt = 1.0
                sm += wt
            for fid, wt in self.itof[k]:
                if binary:
                    wt = 1.0
                self.one_hot[k][fid] = wt / sm

class Graph(object):
    def __init__(self, file_name, entity, weight=None):
        self.vocab_n, self.col_u, self.col_v = entity
        self.col_w = weight
        self.edges = []

        self.node_size = -1

        self.eid2iid = None
        self.iid2eid = None

        self.adj_w = None
        self.adj_t = None

        with open(file_name, 'r') as fi:

            for line in fi:
                items = line.strip().split('\t')

                su, sv = items[self.col_u], items[self.col_v]
                sw = items[self.col_w] if self.col_w != None else None

                u, v = self.vocab_n.stoi.get(su, -1), self.vocab_n.stoi.get(sv, -1)
                w = float(sw) if sw != None else 1

                if u == -1 or v == -1 or w <= 0:
                    continue

                if u == v:
                    continue
                    # print("cindy", u,v,w)

                self.edges += [(u, v, w)]

        self.edges_ss = self.edges

    def get_node_size(self):
        return self.node_size

    def get_edge_size(self):
        return len(self.edges)

    def to_symmetric(self, self_link_weight=1.0):
        vocab = set()
        for u, v, w in self.edges:
            vocab.add(u)
            vocab.add(v)

        pair2wt = dict()
        for u, v, w in self.edges:
            pair2wt[(u, v)] = w

        edges_ = list()
        for (u, v), w in pair2wt.items():
            if u == v:
                continue
            w_ = pair2wt.get((v, u), -1)
            if w > w_:
                edges_ += [(u, v, w), (v, u, w)]
            elif w == w_:
                edges_ += [(u, v, w)]
        for k in vocab:
            edges_ += [(k, k, self_link_weight)]
        
        d = dict()
        for u, v, w in edges_:
            d[u] = d.get(u, 0.0) + w

        self.edges = [(u, v, w/math.sqrt(d[u]*d[v])) for u, v, w in edges_]

    def get_sparse_adjacency(self, cuda=True):
        shape = torch.Size([self.vocab_n.vocab_size, self.vocab_n.vocab_size])

        us, vs, ws = [], [], []
        for u, v, w in self.edges:

            us += [u]
            vs += [v]
            ws += [w]
        index = torch.LongTensor([us, vs])
        value = torch.Tensor(ws)
        if cuda:
            index = index.cuda()
            value = value.cuda()
        adj = torch.sparse.FloatTensor(index, value, shape)
        if cuda:
            adj = adj.cuda()

        return adj

    def to_symmetric_ss(self, self_link_weight=1.0):
        vocab = set()
        for u, v, w in self.edges_ss:
            vocab.add(u)
            vocab.add(v)

        pair2wt = dict()
        for u, v, w in self.edges_ss:
            pair2wt[(u, v)] = w

        edges_ = list()
        for (u, v), w in pair2wt.items():
            if u == v:
                continue
            w_ = pair2wt.get((v, u), -1)
            if w > w_:
                edges_ += [(u, v, w), (v, u, w)]
            elif w == w_:
                edges_ += [(u, v, w)]
        for k in vocab:
            edges_ += [(k, k, self_link_weight)]
        
        d = dict()
        for u, v, w in edges_:
            d[u] = d.get(u, 0.0) + w

        self.edges_ss = [(u, v, w/math.sqrt(d[u]*d[v])) for u, v, w in edges_]

    def get_sparse_adjacency_ss(self, cuda=True):
        shape = torch.Size([self.vocab_n.vocab_size, self.vocab_n.vocab_size])

        us, vs, ws = [], [], []
        for u, v, w in self.edges_ss:

            us += [u]
            vs += [v]
            ws += [w]
        index = torch.LongTensor([us, vs])
        value = torch.Tensor(ws)
        if cuda:
            index = index.cuda()
            value = value.cuda()
        adj = torch.sparse.FloatTensor(index, value, shape)
        if cuda:
            adj = adj.cuda()

        return adj

    def partition(self, nparts):

        node_num = len(self.vocab_n)
        adj_list = [[] for _ in range(node_num)]
        for i, j, _ in self.edges:
            if i == j:
                continue
            if not j in adj_list[i]:
                adj_list[i].append(j)
            if not i in adj_list[j]:
                adj_list[j].append(i)

        _, partition_labels =  metis.part_graph(adj_list, nparts=nparts)
        partition_labels = torch.tensor(partition_labels, dtype=torch.int64)

        return partition_labels
