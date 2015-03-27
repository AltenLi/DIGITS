# Copyright (c) 2014-2015, NVIDIA CORPORATION.  All rights reserved.

import json
import os
import shutil
import tempfile
import time
import unittest

from gevent import monkey
monkey.patch_all()
from bs4 import BeautifulSoup

import numpy as np
from skimage import io
from urlparse import urlparse
from cStringIO import StringIO

import webapp


DUMMY_IMAGE_DIM = 10
DUMMY_IMAGE_COUNT = 10 # per category

# TODO: these might be too short on a slow system
TIMEOUT_DATASET = 10
TIMEOUT_MODEL = 10

def create_dummy_dataset(data_path):
    """
    A very simple dataset - Red, Green and Blue PNGs
    """
    dim = DUMMY_IMAGE_DIM
    count = DUMMY_IMAGE_COUNT
    min_color = 200
    labels = {'red': 0, 'green': 1, 'blue': 2}
    # Stores the relative path of each image of the dataset.
    images = {'red': [], 'green': [], 'blue': []}
    for (label, idx) in labels.iteritems():
        label_path = label
        os.mkdir(os.path.join(data_path, label_path))

        colors = np.linspace(min_color, 255, count)
        for i in range(count):
            pixel = [0, 0, 0]
            pixel[idx] = colors[i]
            img = np.full((dim, dim, 3), pixel, dtype=np.uint8)

            img_path = os.path.join(label_path, str(i) + '.png')
            io.imsave(os.path.join(data_path, img_path), img)
            images[label].append(img_path)

    return images

def get_dummy_network():
    """
    A very simple network - one fully connected layer
    """
    return \
    """
    layer {
        name: "in"
        type: 'InnerProduct'
        bottom: "data"
        top: "in"
        inner_product_param {
            num_output: 3
        }
    }
    layer {
        name: "loss"
        type: "SoftmaxWithLoss"
        bottom: "in"
        bottom: "label"
        top: "loss"
    }
    layer {
        name: "accuracy"
        type: "Accuracy"
        bottom: "in"
        bottom: "label"
        top: "accuracy"
        include {
            phase: TEST
        }
    }
    """


class WebappBaseTest(object):
    """
    Defines some methods useful across the different webapp test suites
    """
    @classmethod
    def setUpClass(cls):
        # Create some dummy data
        cls.data_path = tempfile.mkdtemp()
        cls.images = create_dummy_dataset(cls.data_path)
        # Start up the server
        assert webapp.scheduler.start(), "scheduler wouldn't start"
        webapp.app.config['WTF_CSRF_ENABLED'] = False
        webapp.app.config['TESTING'] = True
        cls.app = webapp.app.test_client()
        cls.created_jobs = []

    @classmethod
    def tearDownClass(cls):
        # Remove all jobs
        for job in cls.created_jobs:
            cls.delete_job(job)
        # Remove the dummy data
        shutil.rmtree(cls.data_path)

    @classmethod
    def create_dataset(cls, **data):
        """
        Create a dataset
        Returns the job_id
        Raises RuntimeError if job fails to create

        Arguments:
        data -- data to be sent with POST request
        """
        if 'dataset_name' not in data:
            data['dataset_name'] = 'dummy_dataset'
        rv = cls.app.post(
                '/datasets/images/classification',
                data = data)
        if not 300 <= rv.status_code <= 310:
            s = BeautifulSoup(rv.data)
            div = s.select('div.alert-danger')
            if div:
                raise RuntimeError(div[0])
            else:
                raise RuntimeError('Failed to create dataset')

        job_id = cls.job_id_from_response(rv)
        assert cls.dataset_exists(job_id), 'dataset not found after successful creation'

        cls.created_jobs.append(job_id)
        return job_id

    @classmethod
    def create_quick_dataset(cls, **kwargs):
        """
        Creates a simple dataset quickly
        Returns the job_id

        Keyword arguments:
        kwargs -- any overrides you want to pass into the POST data
        """
        defaults = {
                'method': 'folder',
                'folder_train': cls.data_path,
                'resize_width': DUMMY_IMAGE_DIM,
                'resize_height': DUMMY_IMAGE_DIM,
                }
        defaults.update(kwargs)
        return cls.create_dataset(**defaults)

    @classmethod
    def create_model(cls, **data):
        """
        Create a model
        Returns the job_id
        Raise RuntimeError if job fails to create

        Arguments:
        data -- data to be sent with POST request
        """
        if 'model_name' not in data:
            data['model_name'] = 'dummy_model'
        rv = cls.app.post(
                '/models/images/classification',
                data = data)
        if not 300 <= rv.status_code <= 310:
            s = BeautifulSoup(rv.data)
            div = s.select('div.alert-danger')
            if div:
                raise RuntimeError(div[0])
            else:
                raise RuntimeError('Failed to create model')

        job_id = cls.job_id_from_response(rv)
        assert cls.model_exists(job_id), 'model not found after successful creation'

        cls.created_jobs.append(job_id)
        return job_id

    @classmethod
    def create_quick_model(cls, dataset_id, **kwargs):
        """
        Creates a simple model quickly
        Returns the job_id

        Arguments:
        dataset_id -- id for the dataset

        Keyword arguments:
        kwargs -- any overrides you want to pass into the POST data
        """
        defaults = {
                'dataset': dataset_id,
                'method': 'custom',
                'custom_network': get_dummy_network(),
                'batch_size': DUMMY_IMAGE_COUNT,
                'train_epochs': 1,
                }
        defaults.update(kwargs)
        return cls.create_model(**defaults)

    @classmethod
    def job_id_from_response(cls, rv):
        """
        Extract the job_id from an HTTP response
        """
        job_url = rv.headers['Location']
        parsed_url = urlparse(job_url)
        return parsed_url.path.split('/')[-1]

    @classmethod
    def dataset_exists(cls, job_id):
        return cls.job_exists(job_id, 'datasets')

    @classmethod
    def model_exists(cls, job_id):
        return cls.job_exists(job_id, 'models')

    @classmethod
    def job_exists(cls, job_id, job_type='jobs'):
        """
        Test whether a job exists
        """
        url = '/%s/%s' % (job_type, job_id)
        rv = cls.app.get(url, follow_redirects=True)
        assert rv.status_code in [200, 404], 'got status code "%s" from "%s"' % (rv.status_code, url)
        return rv.status_code == 200

    @classmethod
    def dataset_status(cls, job_id):
        return cls.job_status(job_id, 'datasets')

    @classmethod
    def model_status(cls, job_id):
        return cls.job_status(job_id, 'models')

    @classmethod
    def job_status(cls, job_id, job_type='jobs'):
        """
        Get the status of a job
        """
        url = '/%s/%s/status' % (job_type, job_id)
        rv = cls.app.get(url)
        assert rv.status_code == 200, 'Cannot get status of job %s. "%s" returned %s' % (job_id, url, rv.status_code)
        status = json.loads(rv.data)
        return status['status']

    @classmethod
    def abort_dataset(cls, job_id):
        return cls.abort_job(job_id, job_type='datasets')

    @classmethod
    def abort_model(cls, job_id):
        return cls.abort_job(job_id, job_type='models')

    @classmethod
    def abort_job(cls, job_id, job_type='jobs'):
        """
        Abort a job
        Returns the HTTP status code
        """
        print 'aborting job %s' % job_id
        rv = cls.app.post('/%s/%s/abort' % (job_type, job_id))
        return rv.status_code

    @classmethod
    def dataset_wait_completion(cls, job_id, **kwargs):
        kwargs['job_type'] = 'datasets'
        if 'timeout' not in kwargs:
            kwargs['timeout'] = TIMEOUT_DATASET
        return cls.job_wait_completion(job_id, **kwargs)

    @classmethod
    def model_wait_completion(cls, job_id, **kwargs):
        kwargs['job_type'] = 'models'
        if 'timeout' not in kwargs:
            kwargs['timeout'] = TIMEOUT_MODEL
        return cls.job_wait_completion(job_id, **kwargs)

    @classmethod
    def job_wait_completion(cls, job_id, timeout=10, polling_period=0.5, job_type='jobs'):
        """
        Poll the job status until it completes
        Returns the final status

        Arguments:
        job_id -- the job to wait for

        Keyword arguments:
        timeout -- maximum wait time (seconds)
        polling_period -- how often to poll (seconds)
        job_type -- [datasets|models]
        """
        start = time.time()
        while True:
            status = cls.job_status(job_id, job_type=job_type)
            if status in ['Done', 'Abort', 'Error']:
                return status
            assert (time.time() - start) < timeout, 'Job took more than %s seconds' % timeout
            time.sleep(polling_period)

    @classmethod
    def delete_dataset(cls, job_id):
        return cls.delete_job(job_id, job_type='datasets')

    @classmethod
    def delete_model(cls, job_id):
        return cls.delete_job(job_id, job_type='models')

    @classmethod
    def delete_job(cls, job_id, job_type='jobs'):
        """
        Delete a job
        Returns the HTTP status code
        """
        print 'deleting job %s' % job_id
        rv = cls.app.delete('/%s/%s' % (job_type, job_id))
        return rv.status_code

################################################################################
# Tests start here
################################################################################

class TestWebapp(WebappBaseTest):
    """
    Some app-wide tests
    """
    def test_page_home(self):
        """home page"""
        rv = self.app.get('/')
        assert rv.status_code == 200, 'page load failed with %s' % rv.status_code
        for h in ['Home', 'Datasets', 'Models']:
            assert h in rv.data, 'unexpected page format'

    def test_invalid_page(self):
        """invalid page"""
        rv = self.app.get('/foo')
        assert rv.status_code == 404, 'should return 404'

    def test_invalid_dataset(self):
        """invalid dataset"""
        assert not self.dataset_exists('foo'), "dataset shouldn't exist"

    def test_invalid_model(self):
        """invalid model"""
        assert not self.model_exists('foo'), "model shouldn't exist"


class TestDatasetCreation(WebappBaseTest):
    """
    Dataset creation tests
    """
    def test_page_dataset_new(self):
        """new image classification dataset page"""
        rv = self.app.get('/datasets/images/classification/new')
        assert rv.status_code == 200, 'page load failed with %s' % rv.status_code
        assert 'New Image Classification Dataset' in rv.data, 'unexpected page format'

    def test_invalid_folder(self):
        """invalid folder"""
        empty_dir = tempfile.mkdtemp()
        try:
            job_id = self.create_dataset(
                    method = 'folder',
                    train_folder = empty_dir
                    )
        except RuntimeError:
            return
        raise AssertionError('Should have failed')

    def test_create_delete(self):
        """create, delete"""
        job_id = self.create_quick_dataset()
        assert self.delete_dataset(job_id) == 200, 'delete failed'
        assert not self.dataset_exists(job_id), 'dataset exists after delete'

    def test_create_wait_delete(self):
        """create, wait, delete"""
        job_id = self.create_quick_dataset()
        assert self.dataset_wait_completion(job_id) == 'Done', 'create failed'
        assert self.delete_dataset(job_id) == 200, 'delete failed'
        assert not self.dataset_exists(job_id), 'dataset exists after delete'

    def test_create_abort_delete(self):
        """create, abort, delete"""
        job_id = self.create_quick_dataset()
        assert self.abort_dataset(job_id) == 200, 'abort failed'
        assert self.delete_dataset(job_id) == 200, 'delete failed'
        assert not self.dataset_exists(job_id), 'dataset exists after delete'


    def create_from_textfiles(self, absolute_path=True):
        """
        Create a dataset from textfiles

        Arguments:
        absolute_path -- if False, give relative paths and image folders
        """
        textfile_train_images = ''
        textfile_labels_file = ''
        label_id = 0
        for (label, images) in self.images.iteritems():
            textfile_labels_file += '%s\n' % label
            for image in images:
                image_path = image
                if absolute_path:
                    image_path = os.path.join(self.data_path, image_path)
                textfile_train_images += '%s %d\n' % (image_path, label_id)

            label_id += 1

        # StringIO wrapping is needed to simulate POST file upload.
        train_upload = (StringIO(textfile_train_images), 'train.txt')
        # Use the same list for training and validation.
        val_upload = (StringIO(textfile_train_images), 'val.txt')
        labels_upload = (StringIO(textfile_labels_file), 'labels.txt')

        data = {
                'method': 'textfile',
                'textfile_train_images': train_upload,
                'textfile_use_val': 'y',
                'textfile_val_images': val_upload,
                'textfile_labels_file': labels_upload,
                }
        if not absolute_path:
            data['textfile_train_folder'] = self.data_path
            data['textfile_val_folder'] = self.data_path

        return self.create_dataset(**data)

    def test_textfile_absolute(self):
        """textfiles (absolute), wait"""
        job_id = self.create_from_textfiles(absolute_path=True)
        assert self.dataset_wait_completion(job_id) == 'Done', 'create failed'

    def test_textfile_relative(self):
        """textfiles (relative), wait"""
        job_id = self.create_from_textfiles(absolute_path=False)
        status = self.dataset_wait_completion(job_id)
        assert status == 'Done', 'create failed "%s"' % status


class TestCreatedDataset(WebappBaseTest):
    """
    Tests on a dataset that has already been created
    """
    pass

class TestModelCreation(WebappBaseTest):
    """
    Model creation tests
    """
    @classmethod
    def setUpClass(cls):
        super(TestModelCreation, cls).setUpClass()
        cls.dataset_id = cls.create_dataset(
                method = 'folder',
                folder_train = cls.data_path,
                resize_width = DUMMY_IMAGE_DIM,
                resize_height = DUMMY_IMAGE_DIM,
                )

    def test_page_model_new(self):
        """new image classification model page"""
        rv = self.app.get('/models/images/classification/new')
        assert rv.status_code == 200, 'page load failed with %s' % rv.status_code
        assert 'New Image Classification Model' in rv.data, 'unexpected page format'

    def test_create_delete(self):
        """create, delete"""
        job_id = self.create_quick_model(self.dataset_id)
        assert self.delete_model(job_id) == 200, 'delete failed'
        assert not self.model_exists(job_id), 'model exists after delete'

    def test_create_wait_delete(self):
        """create, wait, delete"""
        job_id = self.create_quick_model(self.dataset_id)
        assert self.model_wait_completion(job_id) == 'Done', 'create failed'
        assert self.delete_model(job_id) == 200, 'delete failed'
        assert not self.model_exists(job_id), 'model exists after delete'

    def test_create_abort_delete(self):
        """create, abort, delete"""
        job_id = self.create_quick_model(self.dataset_id)
        assert self.abort_model(job_id) == 200, 'abort failed'
        assert self.delete_model(job_id) == 200, 'delete failed'
        assert not self.model_exists(job_id), 'model exists after delete'

class TestCreatedModel(WebappBaseTest):
    """
    Tests on a model that has already been created
    """
    @classmethod
    def setUpClass(cls):
        super(TestCreatedModel, cls).setUpClass()
        cls.dataset_id = cls.create_quick_dataset()
        assert cls.dataset_wait_completion(cls.dataset_id) == 'Done', 'dataset creation failed'
        cls.model_id = cls.create_quick_model(cls.dataset_id)
        assert cls.model_wait_completion(cls.model_id) == 'Done', 'model creation failed'

    def download_model(self, extension):
        rv = self.app.get('/models/%s/download.%s' % (self.model_id, extension))
        assert rv.status_code == 200, 'download failed with %s' % rv.status_code

    def test_download(self):
        """download model"""
        for extension in ['tar', 'zip', 'tar.gz', 'tar.bz2']:
            yield self.download_model, extension

class TestDatasetModelInteractions(WebappBaseTest):
    """
    Test the interactions between datasets and models
    """

    def test_model_with_deleted_database(self):
        """model on deleted dataset"""
        dataset_id = self.create_quick_dataset()
        assert self.delete_dataset(dataset_id) == 200, 'delete failed'
        assert not self.dataset_exists(dataset_id), 'dataset exists after delete'

        try:
            model_id = self.create_quick_model(dataset_id)
        except RuntimeError:
            return
        assert False, 'Should have failed'

    def test_model_on_running_dataset(self):
        """model on running dataset"""
        dataset_id = self.create_quick_dataset()
        model_id = self.create_quick_model(dataset_id)
        # should wait until dataset has finished
        assert self.model_status(model_id) in ['Initialized', 'Waiting', 'Done'], 'model not waiting'
        assert self.dataset_wait_completion(dataset_id) == 'Done', 'dataset creation failed'
        time.sleep(1)
        # then it should start
        assert self.model_status(model_id) in ['Running', 'Done'], "model didn't start"
        self.abort_model(model_id)

    # A dataset should not be deleted while a model using it is running.
    def test_model_create_dataset_delete(self):
        """delete dataset with dependent model"""
        dataset_id = self.create_quick_dataset()
        model_id = self.create_quick_model(dataset_id)
        assert self.dataset_wait_completion(dataset_id) == 'Done', 'dataset creation failed'
        assert self.delete_dataset(dataset_id) == 403, 'dataset deletion should not have succeeded'
        self.abort_model(model_id)

