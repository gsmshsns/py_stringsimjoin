# set similarity join
from six import iteritems
import pandas as pd
import pyprind

from py_stringsimjoin.filter.position_filter import PositionFilter
from py_stringsimjoin.index.position_index import PositionIndex
from py_stringsimjoin.utils.generic_helper import convert_dataframe_to_list, \
    find_output_attribute_indices, get_output_header_from_tables, \
    get_output_row_from_tables, COMP_OP_MAP 
from py_stringsimjoin.utils.simfunctions import get_sim_function
from py_stringsimjoin.utils.token_ordering import \
    gen_token_ordering_for_tables, order_using_token_ordering


def set_sim_join(ltable, rtable,
                 l_key_attr, r_key_attr,
                 l_join_attr, r_join_attr,
                 tokenizer, sim_measure_type, threshold, comp_op,
                 allow_empty,
                 l_out_attrs, r_out_attrs,
                 l_out_prefix, r_out_prefix,
                 out_sim_score, show_progress):
    """Perform set similarity join for a split of ltable and rtable"""

    # find column indices of key attr, join attr and output attrs in ltable
    l_columns = list(ltable.columns.values)
    l_key_attr_index = l_columns.index(l_key_attr)
    l_join_attr_index = l_columns.index(l_join_attr)
    l_out_attrs_indices = find_output_attribute_indices(l_columns, l_out_attrs)

    # find column indices of key attr, join attr and output attrs in rtable
    r_columns = list(rtable.columns.values)
    r_key_attr_index = r_columns.index(r_key_attr)
    r_join_attr_index = r_columns.index(r_join_attr)
    r_out_attrs_indices = find_output_attribute_indices(r_columns, r_out_attrs)

    # convert ltable into a list of tuples
    ltable_list = convert_dataframe_to_list(ltable, l_join_attr_index)

    # convert rtable into a list of tuples
    rtable_list = convert_dataframe_to_list(rtable, r_join_attr_index)

    # generate token ordering using tokens in l_join_attr
    # and r_join_attr
    token_ordering = gen_token_ordering_for_tables(
                         [ltable_list, rtable_list],
                         [l_join_attr_index, r_join_attr_index],
                         tokenizer, sim_measure_type)

    # Build position index on l_join_attr
    position_index = PositionIndex(ltable_list, l_join_attr_index,
                                   tokenizer, sim_measure_type,
                                   threshold, token_ordering)
    # While building the index, we cache the tokens and the empty records.
    # We cache the tokens so that we need not tokenize each string in 
    # l_join_attr multiple times when we need to compute the similarity measure.
    # Further we cache the empty record ids to handle the allow_empty flag.
    cached_data = position_index.build(allow_empty, cache_tokens=True)
    l_empty_records = cached_data['empty_records']
    cached_l_tokens = cached_data['cached_tokens']

    pos_filter = PositionFilter(tokenizer, sim_measure_type, threshold)

    sim_fn = get_sim_function(sim_measure_type)
    comp_fn = COMP_OP_MAP[comp_op]

    output_rows = []
    has_output_attributes = (l_out_attrs is not None or
                             r_out_attrs is not None)

    if show_progress:
        prog_bar = pyprind.ProgBar(len(rtable_list))

    for r_row in rtable_list:
        r_string = r_row[r_join_attr_index]

        r_ordered_tokens = order_using_token_ordering(
                tokenizer.tokenize(r_string), token_ordering)

        if allow_empty and len(r_ordered_tokens) == 0:
            for l_id in l_empty_records:
                if has_output_attributes:
                    output_row = get_output_row_from_tables(
                                     ltable_list[l_id], r_row,
                                     l_key_attr_index, r_key_attr_index,
                                     l_out_attrs_indices,
                                     r_out_attrs_indices)
                else:
                    output_row = [ltable_list[l_id][l_key_attr_index],
                                  r_row[r_key_attr_index]]

                if out_sim_score:
                    output_row.append(1.0)
                output_rows.append(output_row)
            continue
            
        candidate_overlap = pos_filter.find_candidates(r_ordered_tokens,
                                                       position_index)

        for cand, overlap in iteritems(candidate_overlap):
            if overlap > 0:
                l_ordered_tokens = cached_l_tokens[cand]
                sim_score = sim_fn(l_ordered_tokens, r_ordered_tokens)
                if comp_fn(sim_score, threshold):
                    if has_output_attributes:
                        output_row = get_output_row_from_tables(
                                         ltable_list[cand], r_row,
                                         l_key_attr_index, r_key_attr_index,
                                         l_out_attrs_indices,
                                         r_out_attrs_indices)
                    else:
                        output_row = [ltable_list[cand][l_key_attr_index],
                                      r_row[r_key_attr_index]]

                    if out_sim_score:
                        output_row.append(sim_score)
                    output_rows.append(output_row)

        if show_progress:
            prog_bar.update()

    output_header = get_output_header_from_tables(
                        l_key_attr, r_key_attr,
                        l_out_attrs, r_out_attrs,
                        l_out_prefix, r_out_prefix)
    if out_sim_score:
        output_header.append("_sim_score")

    # generate a dataframe from the list of output rows
    output_table = pd.DataFrame(output_rows, columns=output_header)
    return output_table
