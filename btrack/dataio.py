#!/usr/bin/env python
#-------------------------------------------------------------------------------
# Name:     BayesianTracker
# Purpose:  A multi object tracking library, specifically used to reconstruct
#           tracks in crowded fields. Here we use a probabilistic network of
#           information to perform the trajectory linking. This method uses
#           positional and visual information for track linking.
#
# Authors:  Alan R. Lowe (arl) a.lowe@ucl.ac.uk
#
# License:  See LICENSE.md
#
# Created:  14/08/2014
#-------------------------------------------------------------------------------


__author__ = "Alan R. Lowe"
__email__ = "code@arlowe.co.uk"

import re
import os
import csv
import h5py
import json
import logging

# import core
from . import btypes
from . import constants

import numpy as np

from collections import OrderedDict
from functools import wraps



# get the logger instance
logger = logging.getLogger('worker_process')


class _PyTrackObjectFactory:
    def __init__(self):
        raise DeprecationWarning('_PyTrackObjectFactory will be deprecated.')
        self.reset()

    def get(self, txyz, label=None, obj_type=0):
        """ get an instatiated object """
        assert(isinstance(txyz, np.ndarray))
        assert(txyz[0] >= 0.) # assert that time is always positive!
        if label is not None:
            if isinstance(label, int):
                class_label = label
                probability = np.zeros((1,))
            else:
                class_label = label[0].astype(np.uint32)
                probability = label[1:].astype(np.float32)
        else:
            class_label = constants.States.NULL.value
            probability = np.zeros((1,))

        new_object = btypes.PyTrackObject()
        new_object.ID = self._ID
        new_object.t = txyz[0].astype(np.uint32)
        new_object.x = txyz[1].astype(np.float32)
        new_object.y = txyz[2].astype(np.float32)
        new_object.z = txyz[3].astype(np.float32)
        new_object.dummy = False
        new_object.label = class_label          # from the classifier
        new_object.probability = probability
        new_object.type = int(obj_type)

        self._ID += 1
        return new_object

    def reset(self):
        self._ID = 0

# instatiate the factory
# ObjectFactory = _PyTrackObjectFactory()




def localizations_to_objects(localizations):

    """ take a numpy array or pandas dataframe and convert to PyTrackObjects

    Params:
        localizations: list(PyTrackObject), np.ndarray, pandas.DataFrame

    """

    logger.info(f'Objects are of type: {type(localizations)}')

    if isinstance(localizations, list):
        if all([isinstance(l, btypes.PyTrackObject) for l in localizations]):
            # if these are already PyTrackObjects just silently return
            return localizations

    # do we have a numpy array or pandas dataframe?
    if isinstance(localizations, np.ndarray):
        return objects_from_array(localizations)
    else:
        try:
            objects_dict = {c: np.asarray(localizations[c]) for c in localizations}
        except:
            logger.error(f'Unknown localization type: {type(localizations)}')
            raise TypeError(f'Unknown localization type: {type(localizations)}')

    # how many objects are there
    n_objects = objects_dict['t'].shape[0]
    objects_dict['ID'] = np.arange(n_objects)

    return objects_from_dict(objects_dict)



def objects_from_dict(objects_dict: dict):
    """Construct PyTrackObjects from a dictionary"""
    # now that we have the object dictionary, convert this to objects
    objects = []
    n_objects = int(objects_dict['t'].shape[0])

    assert all([v.shape[0] == n_objects for k, v in objects_dict.items()])

    for i in range(n_objects):
        data = {k: v[i] for k, v in objects_dict.items()}
        obj = btypes.PyTrackObject.from_dict(data)
        objects.append(obj)
    return objects

def objects_from_array(objects_arr: np.ndarray,
                       default_keys = constants.DEFAULT_OBJECT_KEYS):
    """Construct PyTrackObjects from a numpy array"""
    assert objects_arr.ndim == 2

    n_features = objects_arr.shape[1]
    assert n_features >= 3

    n_objects = objects_arr.shape[0]

    keys = default_keys[:n_features]
    objects_dict = {keys[i]: objects_arr[:, i] for i in range(n_features)}
    objects_dict['ID'] = np.arange(n_objects)
    return objects_from_dict(objects_dict)



def import_JSON(filename: str):
    """ generic JSON importer for localisations from other software """
    with open(filename, 'r') as json_file:
        data = json.load(json_file)
    objects = []

    for i, _obj in enumerate(data.values()):
        _obj.update({'ID': i})
        obj = btypes.PyTrackObject.from_dict(_obj)
        objects.append(obj)

    return objects


def import_CSV(filename: str):
    """ import from a CSV file

    CSV file should have one of the following formats:

    t, x, y
    t, x, y, label
    t, x, y, z
    t, x, y, z, label

    """

    objects = []
    with open(filename, 'r') as csv_file:
        csvreader = csv.DictReader(csv_file,
                                   delimiter=',',
                                   quotechar='|')
        for i, row in enumerate(csvreader):
            data = {k: float(v) for k,v in row.items()}
            data.update({'ID': i})
            obj = btypes.PyTrackObject.from_dict(data)
            objects.append(obj)
    return objects




def export_delegator(filename, tracker, obj_type=None, filter_by=None):
    """ Export data from the tracker using the appropriate exporter """
    # assert(isinstance(tracker, BayesianTracker))
    assert(isinstance(filename, str))

    export_dir, export_fn = os.path.split(filename)
    _, ext = os.path.splitext(filename)

    assert(os.path.exists(export_dir))

    if ext == '.json':
        raise DeprecationWarning('JSON export is deprecated')
    elif ext == '.mat':
        raise DeprecationWarning('MATLAB export is deprecated')
    elif ext == '.csv':
        export_CSV(filename, tracker.tracks, obj_type=obj_type)
    elif ext in ('.hdf', '.hdf5', '.h5'):
        _export_HDF(filename, tracker, obj_type=obj_type, filter_by=filter_by)
    else:
        logger.error(f'Export file format {ext} not recognized.')





def check_track_type(tracks):
    # return isinstance(tracks[0], btypes.Tracklet)
    return all([isinstance(t, btypes.Tracklet) for t in tracks])



def export_CSV(filename: str,
               tracks: list,
               properties: list = constants.DEFAULT_EXPORT_PROPERTIES,
               obj_type=None):
    """ export the track data as a simple CSV file """

    if not tracks:
        logger.error(f'No tracks found when exporting to: {filename}')
        return

    if not check_track_type(tracks):
        logger.error('Tracks of incorrect type')

    logger.info(f'Writing out CSV files to: {filename}')
    export_track = np.vstack([t.to_array(properties) for t in tracks])

    with open(filename, 'w', newline='') as csv_file:
        csvwriter = csv.writer(csv_file, delimiter=' ')
        csvwriter.writerow(properties)
        for i in range(export_track.shape[0]):
            csvwriter.writerow(export_track[i,:].tolist())




def export_LBEP(filename: str, tracks: list):
    """ export the LBEP table described here:
    https://public.celltrackingchallenge.net/documents/
        Naming%20and%20file%20content%20conventions.pdf
    """
    if not tracks:
        logger.error(f'No tracks found when exporting to: {filename}')
        return

    if not check_track_type(tracks):
        logger.error('Tracks of incorrect type')

    tracks.sort(key=lambda t: t.ID)
    if not filename.endswith('.txt'): filename+='.txt'
    with open(filename, 'w') as lbep_file:
        logger.info(f'Writing LBEP file: {filename}...')
        for track in tracks:
            lbep = f'{track.ID} {track.t[0]} {track.t[-1]} {track.parent}'
            lbep_file.write(f'{lbep}\n')



def _export_HDF(filename: str,
               tracker,
               obj_type=None,
               filter_by: str = None):
    """ export to HDF """
    with HDF5FileHandler(filename, read_write='a', obj_type=obj_type) as hdf:
        hdf.write_tracks(tracker, f_expr=filter_by)



def h5check_property_exists(property):
    """ Wrapper for hdf handler to make sure a property exists """
    def func(fn):
        @wraps(fn)
        def wrapped_handler_property(*args, **kwargs):
            self = args[0]
            assert(isinstance(self, HDF5FileHandler))
            if property not in self._hdf:
                logger.error(f'{property.capitalize()} not found in {self.filename}')
                return None
            return fn(*args, **kwargs)
        return wrapped_handler_property
    return func



class HDF5FileHandler:
    """HDF5 File Handler.

    Generic HDF5 file hander for reading and writing datasets. This is
    inter-operable between segmentation, tracking and analysis code.

    LBEPR is a modification of the LBEP format to also include the root node
    of the tree.

        I - number of objects
        J - number of frames
        K - number of tracks

    Added generic filtering to object retrieval, e.g.
        obj = handler.filtered_objects('flag==1')
        retrieves all objects if there is an object['flag'] == 1

    Basic format of the HDF file is:
        segmentation/
            images          - (J x (d) x h x w) uint16 segmentation
        objects/
            obj_type_1/
                coords      - (I x 5) [t, x, y, z, object_type]
                labels      - (I x D) [label, (softmax scores ...)]
                map         - (J x 2) [start_index, end_index] -> coords array
                properties  - (I x D) [property-0, ..., property-D]
            ...
        tracks/
            obj_type_1/
                tracks      - (I x 1) [index into coords]
                dummies     - similar to coords, but for dummy objects
                map         - (K x 2) [start_index, end_index] -> tracks array
                LBEPRG      - (K x 6) [L, B, E, P, R, G]
                fates       - (K x n) [fate_from_tracker, ...future_expansion]
            ...


    Parameters
    ----------
    segmentation : np.ndarray
    objects : list [PyTrackObject]
    filtered_objects  : np.ndarray
    properties : np.ndarray
    tracks : list [Tracklet]
    lbep : np.ndarray

    Methods
    -------


    Usage
    -----

    > with HDF5FileHandler('file.h5', 'r') as h:
    >    objects = h.objects

    """

    def __init__(self,
                 filename: str,
                 read_write: str = 'r',
                 object_type: str = 'obj_type_1'):

        self._f_expr = None # DO NOT USE
        self._object_type = None
        self.object_type = object_type

        self.filename = filename
        logger.info(f'Opening HDF file: {self.filename}')
        self._hdf = h5py.File(filename, read_write)
        self._states = list(constants.States)

    @property
    def object_types(self):
        return list(self._hdf['objects'].keys())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        if not self._hdf: return
        logger.info(f'Closing HDF file: {self.filename}')
        self._hdf.close()



    @property
    def object_type(self) -> str:
        return self._object_type
    @object_type.setter
    def object_type(self, obj_type: str):
        if not obj_type.startswith('obj_type_'):
            raise ValueError('Object type must start with ``obj_type_``.')
        self._object_type = obj_type


    @property
    @h5check_property_exists('segmentation')
    def segmentation(self):
        return self._hdf['segmentation']['images'][:].astype(np.uint16)

    def write_segmentation(self, segmentation: np.ndarray):
        """Write out the segmentation to an HDF file."""
        # write the segmentation out
        grp = self._hdf.create_group('segmentation')
        grp.create_dataset(f'images',
                           data=segmentation,
                           dtype='uint16',
                           compression='gzip',
                           compression_opts=7)

    @property
    def objects(self):
        """Return the objects in the file."""
        return self.filtered_objects()

    @h5check_property_exists('objects')
    def filtered_objects(self, f_expr=None):
        """ return a filtered list of objects based on metadata.
        f_expr should be of the format 'flag==1'
        """

        if self.object_type not in self.object_types:
            raise ValueError(f'Object type {self.object_type} not recognized')

        # read the whole dataset into memory
        txyz = self._hdf['objects'][self.object_type]['coords'][:]
        if 'labels' not in self._hdf['objects'][self.object_type]:
            logger.warning('Labels missing from objects in HDF file')
            labels = np.zeros((txyz.shape[0], 6))
        else:
            labels = self._hdf['objects'][self.object_type]['labels'][:]

        # note that this doesn't do much error checking at the moment
        if f_expr is not None:
            assert isinstance(f_expr, str)
            pattern = '(?P<name>\w+)(?P<op>[\>\<\=]+)(?P<cmp>[0-9]+)'
            m = re.match(pattern, f_expr)
            f_eval = f'x{m["op"]}{m["cmp"]}' # e.g. x > 10

            if m['name'] in self._hdf['objects'][self.object_type]:
                data = self._hdf['objects'][self.object_type][m['name']][:]
                filtered_idx = [i for i, x in enumerate(data) if eval(f_eval)]
            else:
                logger.warning(f'Cannot filter objects by {m["name"]}')
        else:
            filtered_idx = range(txyz.shape[0]) # default filtering uses all

        # sanity check that coordinates matches labels
        assert txyz.shape[0] == labels.shape[0]
        logger.info(f'Loading {self.object_type} {txyz.shape} '
                    f'({len(filtered_idx)} filtered: {f_expr})...')

        txyz_filtered = txyz[filtered_idx, :]
        labels_filtered = labels[filtered_idx, :]

        objects_dict = {'t': txyz_filtered[:, 0],
                        'x': txyz_filtered[:, 1],
                        'y': txyz_filtered[:, 2],
                        'z': txyz_filtered[:, 3],
                        'label': labels_filtered[:, 0],
                        'ID': np.asarray(filtered_idx),}

        return objects_from_dict(objects_dict)


    def write_objects(self, tracker):
        """Write objects to HDF file."""
        #TODO(arl): make sure that the objects are ordered in time

        self._hdf.create_group('objects')
        grp = self._hdf['objects'].create_group(self.object_type)

        n_objects = len(tracker.objects)
        n_frames = np.max([o.t for o in tracker.objects]) + 1

        txyz = np.zeros((n_objects, 5), dtype=np.float32)
        labels = np.zeros((n_objects, 1), dtype=np.uint8)
        fmap = np.zeros((n_frames, 2), dtype=np.uint32)

        # convert the btrack objects into a numpy array
        for i, obj in enumerate(tracker.objects):
            txyz[i, :] = [obj.t, obj.x, obj.y, obj.z, 0]
            labels[i, :] = obj.label
            t = int(obj.t)
            fmap[t, 1] = np.max([fmap[t, 1], i])
        fmap[1:, 0] = fmap[:-1, 1]

        grp.create_dataset('coords', data=txyz, dtype='float32')
        grp.create_dataset('labels', data=labels, dtype='float32')
        grp.create_dataset('map', data=fmap, dtype='uint32')


    @property
    @h5check_property_exists('tracks')
    def tracks(self):
        """Return the tracks in the file."""

        logger.info(f'Loading tracks: {self.object_type}...')
        track_map = self._hdf['tracks'][self.object_type]['map'][:]
        track_refs = self._hdf['tracks'][self.object_type]['tracks'][:]
        lbep = self._hdf['tracks'][self.object_type]['LBEPR'][:]
        fates = self._hdf['tracks'][self.object_type]['fates'][:]

        # if there are dummies, make new dummy objects
        if 'dummies' in self._hdf['tracks'][self.object_type]:
            dummies = self._hdf['tracks'][self.object_type]['dummies'][:]
            dummy_obj = objects_from_array(dummies[:, :4])
            for d in dummy_obj:
                d.ID = -(d.ID+1)    # restore the -ve ID
                d.dummy = True      # set the dummy flag to true

        # TODO(arl): this needs to be stored in the HDF folder
        if 'f_expr' in self._hdf['tracks'][self.object_type].attrs:
            f_expr = self._hdf['tracks'][self.object_type].attrs['f_expr']
        elif self._f_expr is not None:
            f_expr = self._f_expr
        else:
            f_expr = None

        obj = self.filtered_objects(f_expr=f_expr)

        def _get_txyz(_ref):
            if _ref>=0:
                return obj[_ref]
            return dummy_obj[abs(_ref)-1] # references are -ve for dummies

        tracks = []
        for i in range(track_map.shape[0]):
            idx = slice(*track_map[i, :].tolist())
            refs = track_refs[idx]
            track = btypes.Tracklet(lbep[i, 0], list(map(_get_txyz, refs)))
            track.parent = lbep[i, 3]    # set the parent and root of tree
            track.root = lbep[i, 4]
            if lbep.shape[1] > 5: track.generation = lbep[i, 5]
            track.fate = constants.Fates(fates[i]) # restore the track fate
            tracks.append(track)

        # once we have all of the tracks, populate the children
        to_update = {}
        for track in tracks:
            if not track.is_root:
                parents = filter(lambda t: t.ID == track.parent, tracks)
                for parent in parents:
                    if parent not in to_update:
                        to_update[parent] = []
                    to_update[parent].append(track.ID)

        # sanity check, can be removed at a later date
        assert all([len(children)<=2 for children in to_update.values()])

        # add the children to the parent
        for track, children in to_update.items():
            track.children = children

        return tracks


    def write_tracks(self, tracker, f_expr=None):
        """Write tracks to HDF file."""
        if not tracker.tracks:
            logger.error(f'No tracks found when exporting to: {self.filename}')
            return

        tracks = tracker.refs
        dummies = tracker.dummies
        lbep_table = np.stack(tracker.lbep, axis=0).astype(np.int32)

        # sanity check
        assert lbep_table.shape[0] == len(tracks)

        logger.info(f'Writing tracks to HDF file: {self.filename}')
        hdf_tracks = np.concatenate(tracks, axis=0)

        hdf_frame_map = np.zeros((len(tracks),2), dtype=np.int32)
        for i, track in enumerate(tracks):
            if i > 0:
                offset = hdf_frame_map[i-1,1]
            else: offset = 0
            hdf_frame_map[i, :] = np.array([0, len(track)]) + offset

        if 'tracks' not in self._hdf:
            self._hdf.create_group('tracks')

        if self.obj_type in self._hdf['tracks']:
            logger.warning(f'Removing {self.obj_type} from HDF file. ')
            del self._hdf['tracks'][self.obj_type]

        grp = self._hdf['tracks'].create_group(self.obj_type)
        grp.create_dataset('tracks', data=hdf_tracks, dtype='int32')
        grp.create_dataset('map', data=hdf_frame_map, dtype='uint32')

        # if we have used the f_expr we can save it as an attribute here
        if f_expr is not None and isinstance(f_expr, str):
            grp.attrs['f_expr'] = f_expr

        # also save the version number as an attribute
        grp.attrs['version'] = constants.get_version()

        # write out dummies
        if dummies:
            logger.info(f'Writing dummies to HDF file: {self.filename}')
            o = self.object_types.index(self.obj_type) + 1
            txyz = np.stack([[d.t, d.x, d.y, d.z, o] for d in dummies], axis=0)
            grp.create_dataset('dummies', data=txyz, dtype='float32')

        # write out the LBEP table
        logger.info(f'Writing LBEPR to HDF file: {self.filename}')
        grp.create_dataset('LBEPR', data=lbep_table, dtype='int32')

        # write out cell fates
        logger.info(f'Writing track fates to HDF file: {self.filename}')
        fate_table = np.stack([t.fate.value for t in tracker.tracks], axis=0)
        grp.create_dataset('fates', data=fate_table, dtype='int32')

    @property
    @h5check_property_exists('tracks')
    def lbep(self):
        """Return the LBEP data."""
        logger.info('Loading LBEPR tables...')
        return self._hdf['tracks'][self.obj_type]['LBEPR'][:]






if __name__ == "__main__":
    pass
