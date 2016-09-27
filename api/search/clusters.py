'''Cluster-related search options'''

from sqlalchemy import (
    or_,
    sql,
)
from .helpers import (
    break_lines,
    register_handler,
)
from api.models import (
    db,
    AsDomain,
    AsDomainProfile,
    BgcType,
    BiosyntheticGeneCluster as Bgc,
    Compound,
    Gene,
    Genome,
    DnaSequence,
    Locus,
    Monomer,
    Profile,
    ProfileHit,
    Taxa,
    t_gene_cluster_map,
    t_rel_clusters_compounds,
    t_rel_clusters_types,
    RelCompoundsMonomer,
)

CLUSTERS = {}
CLUSTER_FORMATTERS = {}


@register_handler(CLUSTER_FORMATTERS)
def clusters_to_json(clusters):
    '''Convert model.BiosyntheticGeneClusters into JSON'''
    json_clusters = []
    for cluster in clusters:
        json_cluster = {}
        json_cluster['bgc_id'] = cluster.bgc_id
        json_cluster['cluster_number'] = cluster.cluster_number

        json_cluster['start_pos'] = cluster.locus.start_pos
        json_cluster['end_pos'] = cluster.locus.end_pos

        json_cluster['acc'] = cluster.locus.sequence.acc
        json_cluster['version'] = cluster.locus.sequence.version

        json_cluster['genus'] = cluster.locus.sequence.genome.tax.genus
        json_cluster['species'] = cluster.locus.sequence.genome.tax.species
        json_cluster['strain'] = cluster.locus.sequence.genome.tax.strain

        term = '-'.join([t.term for t in cluster.bgc_types])
        if len(cluster.bgc_types) == 1:
            json_cluster['description'] = cluster.bgc_types[0].description
            json_cluster['term'] = term
        else:
            json_cluster['description'] = 'Hybrid cluster: {}'.format(term)
            json_cluster['term'] = '{} hybrid'.format(term)

        json_cluster['similarity'] = None
        json_cluster['cbh_description'] = None
        json_cluster['cbh_acc'] = None

        knownclusterblasts = [hit for hit in cluster.clusterblast_hits if hit.algorithm.name == 'knownclusterblast']
        if len(knownclusterblasts) > 0:
            json_cluster['similarity'] = knownclusterblasts[0].similarity
            json_cluster['cbh_description'] = knownclusterblasts[0].description
            json_cluster['cbh_acc'] = knownclusterblasts[0].acc

        json_clusters.append(json_cluster)
    return json_clusters


@register_handler(CLUSTER_FORMATTERS)
def clusters_to_csv(clusters):
    '''Convert model.BiosyntheticGeneClusters into CSV'''
    json_clusters = clusters_to_json(clusters)
    csv_lines = ['#Genus\tSpecies\tNCBI accession\tCluster number\tBGC type\tFrom\tTo\tMost similar known cluster\tSimilarity in %\tMIBiG BGC-ID\tResults URL']
    for cluster in json_clusters:
        csv_lines.append('{genus}\t{species}\t{acc}.{version}\t{cluster_number}\t{term}\t{start_pos}\t{end_pos}\t'
                         '{cbh_description}\t{similarity}\t{cbh_acc}\t'
                         'http://antismash-db.secondarymetabolites.org/output/{acc}/index.html#cluster-{cluster_number}'.format(**cluster))
    return csv_lines


@register_handler(CLUSTER_FORMATTERS)
def clusters_to_fasta(clusters):
    '''Convert model.BiosyntheticGeneCluster into FASTA'''
    fasta_records = []
    for cluster in clusters:
        compiled_type = '-'.join([t.term for t in cluster.bgc_types])
        seq = break_lines(cluster.locus.sequence.dna)
        fasta = '>{c.locus.sequence.acc}.{c.locus.sequence.version}|Cluster {c.cluster_number}|' \
                '{compiled_type}|{c.locus.start_pos}-{c.locus.end_pos}|' \
                '{c.locus.sequence.genome.tax.genus} {c.locus.sequence.genome.tax.species} ' \
                '{c.locus.sequence.genome.tax.strain}\n{seq}' \
                .format(c=cluster, compiled_type=compiled_type, seq=seq)
        fasta_records.append(fasta)

    return fasta_records


def cluster_query_from_term(term):
    '''Recursively generate an SQL query from the search terms'''
    if term.kind == 'expression':
        if term.category == 'unknown':
            term.category = guess_cluster_category(term)
        if term.category in CLUSTERS:
            return CLUSTERS[term.category](term.term)
        else:
            return Bgc.query.filter(sql.false())
    elif term.kind == 'operation':
        left_query = cluster_query_from_term(term.left)
        right_query = cluster_query_from_term(term.right)
        if term.operation == 'except':
            return left_query.except_(right_query)
        elif term.operation == 'or':
            return left_query.union(right_query)
        elif term.operation == 'and':
            return left_query.intersect(right_query)

    return Bgc.query.filter(sql.false())


def guess_cluster_category(term):
    '''Guess cluster search category from term'''
    if BgcType.query.filter(BgcType.term.ilike(term.term)).count() > 0:
        return 'type'
    if DnaSequence.query.filter(DnaSequence.acc.ilike(term.term)).count() > 0:
        return 'acc'
    if Taxa.query.filter(Taxa.genus.ilike(term.term)).count() > 0:
        return 'genus'
    if Taxa.query.filter(Taxa.species.ilike(term.term)).count() > 0:
        return 'species'

    return term.category


@register_handler(CLUSTERS)
def clusters_by_type(term):
    '''Return a query for a bgc by type or type description search'''
    all_subtypes = db.session.query(BgcType).filter(or_(BgcType.term == term, BgcType.description.ilike('%{}%'.format(term)))).cte(recursive=True)
    all_subtypes = all_subtypes.union(db.session.query(BgcType).filter(BgcType.parent_id == all_subtypes.c.bgc_type_id))
    return db.session.query(Bgc).join(t_rel_clusters_types).join(all_subtypes)


@register_handler(CLUSTERS)
def clusters_by_strain(term):
    '''Return a query for a bgc by strain search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.strain.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_species(term):
    '''Return a query for a bgc by species search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.species.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_genus(term):
    '''Return a query for a bgc by genus search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.genus.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_family(term):
    '''Return a query for a bgc by family search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.family.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_order(term):
    '''Return a query for a bgc by order search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.taxonomic_order.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_class(term):
    '''Return a query for a bgc by class search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa._class.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_phylum(term):
    '''Return a query for a bgc by phylum search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.phylum.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_superkingdom(term):
    '''Return a query for a bgc by superkingdom search'''
    return Bgc.query.join(Locus).join(DnaSequence).join(Genome).join(Taxa).filter(Taxa.superkingdom.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_monomer(term):
    '''Return a query for a bgc by monomer or monomer description search'''
    return Bgc.query.join(t_rel_clusters_compounds).join(RelCompoundsMonomer, t_rel_clusters_compounds.c.compound_id == RelCompoundsMonomer.compound_id).join(Monomer).filter(
        or_(Monomer.name.ilike(term), Monomer.description.ilike('%{}%'.format(term))))


@register_handler(CLUSTERS)
def clusters_by_acc(term):
    '''Return a query for a bgc by accession number search'''
    return Bgc.query.join(Locus).join(DnaSequence).filter(DnaSequence.acc.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_compoundseq(term):
    '''Return a query for a bgc by compound sequence search'''
    return Bgc.query.join(t_rel_clusters_compounds).join(Compound).filter(Compound.peptide_sequence.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def clusters_by_compoundclass(term):
    '''Return a query for a bgc by compound class'''
    return Bgc.query.join(t_rel_clusters_compounds).join(Compound).filter(Compound._class.ilike(term))


@register_handler(CLUSTERS)
def cluster_by_profile(term):
    '''Return a query for a bgc by profile name'''
    return Bgc.query.join(t_gene_cluster_map, t_gene_cluster_map.c.bgc_id == Bgc.bgc_id) \
                    .join(Gene, t_gene_cluster_map.c.gene_id == Gene.gene_id) \
                    .join(ProfileHit).join(Profile) \
                    .filter(Profile.name.ilike('%{}%'.format(term)))


@register_handler(CLUSTERS)
def cluster_by_asdomain(term):
    '''Return a query for a bgc by asdomain name'''
    return Bgc.query.join(t_gene_cluster_map, t_gene_cluster_map.c.bgc_id == Bgc.bgc_id) \
                    .join(Gene, t_gene_cluster_map.c.gene_id == Gene.gene_id) \
                    .join(AsDomain).join(AsDomainProfile) \
                    .filter(AsDomainProfile.name.ilike(term))